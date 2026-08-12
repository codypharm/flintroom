"""The meter — the sweep that charges live interrogation as it is consumed.

A periodic job rather than a timer per room, for the reason the reaper is one
too: a per-session task lives in one process, and a restart or an ordinary
deploy would silently stop billing every room that was open while the voice
provider carried on invoicing us. A sweep that derives what it owes from the
clock catches up after a missed beat and costs nothing when it runs twice.

Which is the other half of the design: `tick_index` is a function of how long
the interrogation span has been open, not a counter the sweep keeps. Two workers
sweeping the same session compute the same index and the ledger's idempotency
does the rest.

Room age is set by backdating the span rather than by moving Python's clock —
the sweep asks Postgres how long the room has been open, so Postgres is the
only clock in the comparison.
"""

import uuid
from datetime import timedelta

from sqlalchemy import func, update

from app.modules.billing.models import Account
from app.modules.billing.schemas import Bucket, EntryReason
from app.modules.billing.service import LedgerService
from app.modules.sessions.models import Session as SessionModel
from app.modules.sessions.models import SessionPhaseSpan
from app.modules.sessions.schemas import EndReason, SessionState
from app.modules.sessions.service import SessionService


async def _running_for(db, session, *, seconds: int) -> None:
    """Make the open interrogation span look `seconds` old."""
    await db.execute(
        update(SessionPhaseSpan)
        .where(
            SessionPhaseSpan.session_id == session.id,
            SessionPhaseSpan.ended_at.is_(None),
        )
        .values(started_at=func.now() - timedelta(seconds=seconds))
    )
    await db.commit()


async def _in_grace_for(db, session, *, seconds: int) -> None:
    """Backdate the grace clock, leaving everything else alone."""
    await db.execute(
        update(SessionModel)
        .where(SessionModel.id == session.id)
        .values(grace_started_at=func.now() - timedelta(seconds=seconds))
    )
    await db.commit()


async def _grant(ledger, account, seconds: int) -> None:
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=seconds,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )


async def test_a_sweep_that_missed_its_beat_catches_up(
    meter, sessions, ledger, account, db
):
    """A late sweep bills what was served, not what it happened to notice.

    This is the reason the index is derived from the clock instead of counted:
    a worker that was restarted, blocked, or redeployed comes back and charges
    the intervals that elapsed while it was away. A counter would resume from
    where it stopped and hand the user every minute the outage covered.
    """
    await _grant(ledger, account, 600)
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await _running_for(db, session, seconds=45)

    await meter.sweep()

    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == 555
    # Three intervals, three entries — the trail records which minutes were
    # spent, not only how many, so a caught-up sweep must not collapse them
    # into one lump the user cannot reconcile against a room they were in.
    ticks = [
        entry
        for entry in await ledger.entries(user_id=account.user_id)
        if entry.reason is EntryReason.TICK
    ]
    assert [entry.delta_seconds for entry in ticks] == [-15, -15, -15]


async def test_a_room_closing_mid_sweep_does_not_stop_the_billing_run(
    meter, sessions, ledger, account, db, monkeypatch
):
    """One room lost to a race must not cost every other room its minutes.

    The sweep selects live rooms and then bills them one at a time, and a user
    pressing End lands in that gap constantly — it is the most ordinary race in
    the product. Letting it escape would abandon every room later in the batch,
    and because the index is derived rather than counted, those rooms are not
    lost so much as deferred: the next sweep bills them anyway, in a bigger
    batch, behind the same contention. The failure compounds instead of clearing.
    """
    other = Account(user_id=uuid.uuid4(), entitlement_tier="free")
    db.add(other)
    await db.commit()
    # Read before anything can roll back: a rollback expires every ORM object
    # on this session, and touching one afterwards reloads it lazily mid-test.
    owner, other_owner = account.user_id, other.user_id

    for user_id in (owner, other_owner):
        await ledger.grant(
            user_id=user_id,
            bucket=Bucket.ALLOWANCE,
            seconds=600,
            reason=EntryReason.GRANT_ALLOWANCE,
            idempotency_key=f"grant-{user_id}",
        )
        session = await sessions.start(user_id=user_id)
        await sessions.activate(session_id=session.id)
        await _running_for(db, session, seconds=15)

    # Whichever room the sweep reaches first, the user ends it underneath.
    original = LedgerService.charge_tick
    closed_one = []

    async def user_pressed_end(self, *, user_id, session_id, tick_index, seconds):
        if not closed_one:
            closed_one.append(user_id)
            await SessionService(db).begin_finalizing(
                session_id=session_id, end_reason=EndReason.USER_ENDED
            )
        return await original(
            self,
            user_id=user_id,
            session_id=session_id,
            tick_index=tick_index,
            seconds=seconds,
        )

    monkeypatch.setattr(LedgerService, "charge_tick", user_pressed_end)
    await meter.sweep()
    monkeypatch.undo()

    survivor = next(u for u in (owner, other_owner) if u != closed_one[0])
    assert (await ledger.balance(user_id=survivor)).allowance_seconds == 585


async def test_a_room_left_running_is_closed_at_the_session_cap(
    meter, sessions, ledger, account, db
):
    """A forgotten room has to stop by itself.

    The user with minutes in the bank is exactly who this protects: nothing in
    the balance would ever stop them, so a phone left face-down after the panel
    finished would burn an hour of provider time against a room nobody is in.
    The cap is a bound on that, not a promise about session length — the time
    that genuinely ran is still billed, because it genuinely cost us.
    """
    await _grant(ledger, account, 3600)
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await _running_for(db, session, seconds=12 * 60 + 15)
    # Still arguing back — otherwise this is an abandoned room, which is idle
    # detection's case and a refund, not the cap's case and a full charge.
    await sessions.record_speech(session_id=session.id)

    await meter.sweep()

    closed = await sessions.get(session_id=session.id)
    assert closed.state is SessionState.SETTLED
    assert closed.end_reason is EndReason.SESSION_CAP
    # 735 seconds, not 720: the sweep arrived an interval late and the room was
    # open for every one of them. Billing the cap instead would mean eating time
    # the provider charged us for, and overshoot is bounded by the sweep's own
    # interval — which is the argument for keeping that interval short.
    assert (await ledger.balance(user_id=account.user_id)).total_seconds == 3600 - 735


async def test_a_room_that_runs_out_closes_at_the_grace_cap_and_not_before(
    meter, sessions, ledger, account, db
):
    """Running out is not an ending; running out for two minutes is.

    §4.5 forbids cutting a live interrogation off, so the first overdrawn tick
    changes nothing the user can perceive — the panel keeps going. What it
    starts is the clock, and when that expires the room closes and settles in
    the same pass, which forgives the overdraft and releases the lock so the
    user can go straight into an unmetered debrief.
    """
    await _grant(ledger, account, 10)
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await _running_for(db, session, seconds=15)

    await meter.sweep()

    assert (await ledger.balance(user_id=account.user_id)).total_seconds == -5
    assert (await sessions.get(session_id=session.id)).state is SessionState.ACTIVE

    # Two minutes later, still overdrawing.
    await _in_grace_for(db, session, seconds=180)
    await meter.sweep()

    closed = await sessions.get(session_id=session.id)
    assert closed.state is SessionState.SETTLED
    assert closed.end_reason is EndReason.GRACE_CAP
    # Settled means forgiven, not carried into next month (docs Part 1).
    assert (await ledger.balance(user_id=account.user_id)).total_seconds == 0


async def test_sweeping_the_same_room_twice_bills_it_once(
    meter, sessions, ledger, account, db
):
    """Two workers, or one worker run twice, must reach the same balance.

    Without this the sweep could not be run anywhere but a single process, and
    the whole reason it is a sweep is that a single process is exactly what we
    refuse to depend on. The index is derived, so the second pass recomputes the
    same one and the ledger recognises it.
    """
    await _grant(ledger, account, 600)
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await _running_for(db, session, seconds=15)

    await meter.sweep()
    await meter.sweep()

    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == 585
    assert (
        len([
            entry
            for entry in await ledger.entries(user_id=account.user_id)
            if entry.reason is EntryReason.TICK
        ])
        == 1
    )


async def test_a_room_part_way_through_an_interval_is_not_charged_for_it(
    meter, sessions, ledger, account, db
):
    """In arrears means in arrears: an interval is billed once it is served.

    This is what makes every failure mode undercharge rather than overcharge —
    a crash, a force-quit or a dead network can only ever lose us the current
    interval, never take minutes the user did not get (docs Part 1). Charging
    the interval up front would be a reservation, which §4.5 forbids outright.
    """
    await _grant(ledger, account, 600)
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await _running_for(db, session, seconds=10)

    await meter.sweep()

    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == 600
    assert not [
        entry
        for entry in await ledger.entries(user_id=account.user_id)
        if entry.reason is EntryReason.TICK
    ]


async def test_a_room_that_has_run_an_interval_is_charged_for_it(
    meter, sessions, ledger, account, db
):
    """The tracer: time under fire turns into minutes spent.

    In arrears — the interval is charged once it has elapsed, never before, so a
    crash or a dropped network can only ever undercharge (docs Part 1, Decrement
    cadence). Fifteen seconds of room open, fifteen seconds off the balance.
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=600,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await _running_for(db, session, seconds=15)

    await meter.sweep()

    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == 585
