"""The reaper — the only thing that resolves a session no user will ever fix.

Three cases (docs/minutes-ledger-and-sessions.md Part 3, edge case 6): a stuck
`provisioning`, an orphaned `active`, and a stuck `finalizing`. All three hold
the one-live-session lock, so a session left in any of them silently costs the
user their next rehearsal — and the third is the one no user action resolves,
because the client that would retry has already been told the session ended.

Ages are set by moving the row's timestamp backwards rather than by moving the
clock. The reaper's cutoff is computed by Postgres, so Postgres is the only
clock in the comparison; freezing Python's would prove nothing about it.
"""

import uuid
from datetime import timedelta

import pytest_asyncio
from sqlalchemy import func, update

from app.core.actors import Actor
from .conftest import create_funded_account
from app.core.errors import InvalidStateTransition
from app.modules.audit_log.schemas import AuditEventType
from app.modules.billing.models import Account
from app.modules.billing.schemas import Bucket, EntryReason
from app.modules.sessions.models import Session as SessionModel
from app.modules.sessions.schemas import EndReason, SessionState
from app.modules.sessions.service import SessionService



async def _stall(db, session, *, seconds: int) -> None:
    """Make a session look untouched for `seconds`, without changing its state.

    Backdates the progress mark rather than the start time: a twelve-minute
    interrogation that has just begun settling is old but not stuck, and the
    two must not be confused.
    """
    await db.execute(
        update(SessionModel)
        .where(SessionModel.id == session.id)
        .values(last_progress_at=func.now() - timedelta(seconds=seconds))
    )
    await db.commit()


async def test_a_session_stuck_provisioning_is_failed_so_the_lock_releases(
    reaper, sessions, ledger, funded_account, db
):
    """The tracer: spin-up died, and nobody is coming to tell us.

    `provisioning` bills nothing, so the cost of leaving one stuck is not money
    — it is that the user cannot start another session at all, and has no way
    to clear it themselves. Ending it as `failed` rather than routing it through
    settlement is what keeps a room that never opened out of the cost reports.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await _stall(db, session, seconds=180)

    await reaper.reap()

    reaped = await sessions.get(session_id=session.id)
    assert reaped.state is SessionState.FAILED
    assert reaped.end_reason is EndReason.PROVISIONING_FAILED
    # Nothing billed, rather than no entries: a real account carries its
    # signup grant, and a tick is the only thing that writes against a room.
    entries = await ledger.entries(user_id=funded_account.user_id)
    assert [e for e in entries if e.reason is EntryReason.TICK] == []

    # The point of the whole exercise: the user can start again.
    await sessions.start(user_id=funded_account.user_id)


async def test_a_spin_up_still_in_progress_is_left_alone(reaper, sessions, funded_account):
    """The cutoff has to mean something, or the reaper is a session killer.

    Agent spin-up takes real time, and this runs on a timer with no knowledge of
    who is mid-connection. Reaping early does not merely lose a session: the
    user is holding a phone that believes it is connecting, and the failure they
    see is ours.
    """
    session = await sessions.start(user_id=funded_account.user_id)

    await reaper.reap()

    assert (await sessions.get(session_id=session.id)).state is SessionState.PROVISIONING


async def test_a_reaped_session_is_attributed_to_the_reaper_in_the_audit_trail(
    reaper, sessions, audit, funded_account, db
):
    """The one ending with no user request behind it.

    Every other transition has a caller to point at. This one happens on a
    timer, to a user who is not there, and it is the ending most likely to be
    disputed — "I never ended that session" is correct, and the audit row is the
    only thing that explains what did. `Actor.REAPER` rather than `SYSTEM` so
    the sweep is distinguishable from the tick loop that shares its schedule.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await _stall(db, session, seconds=180)

    await reaper.reap()

    reaped = [
        event
        for event in await audit.events_for_user(user_id=funded_account.user_id)
        if event.event_type is AuditEventType.SESSION_REAPED
    ]
    assert len(reaped) == 1
    assert reaped[0].session_id == session.id
    assert reaped[0].actor is Actor.REAPER
    # What it was stuck in, so an operator can tell a dead spin-up from an
    # abandoned room without joining back to a session row that may be gone.
    assert reaped[0].context["from_state"] == SessionState.PROVISIONING.value
    assert reaped[0].context["end_reason"] == EndReason.PROVISIONING_FAILED.value


async def test_a_settlement_that_died_partway_is_finished_by_the_reaper(
    reaper, sessions, ledger, funded_account, db
):
    """The case no user action will ever resolve.

    The client has already been told the session ended and has moved on; there
    is no screen left showing an End button. Until someone finishes settling,
    the user's grace overdraft stands, the lock is still held, and every attempt
    to start a fresh rehearsal is refused — a user locked out of the product by
    a crash they did not cause and cannot clear.
    """
    await ledger.grant(
        user_id=funded_account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=10,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )
    session = await sessions.start(user_id=funded_account.user_id)
    await sessions.activate(session_id=session.id)
    # §4.5 forbids cutting the panel off, so this ran 20s past zero.
    await ledger.charge_tick(
        user_id=funded_account.user_id, session_id=session.id, tick_index=0, seconds=30
    )
    await sessions.begin_finalizing(
        session_id=session.id, end_reason=EndReason.USER_ENDED
    )
    # ...and the process died here, before settlement wrote anything.
    await _stall(db, session, seconds=180)

    await reaper.reap()

    assert (await sessions.get(session_id=session.id)).state is SessionState.SETTLED
    assert (await ledger.balance(user_id=funded_account.user_id)).allowance_seconds == 0
    await sessions.start(user_id=funded_account.user_id)


async def test_a_room_whose_client_vanished_is_closed_without_a_refund(
    reaper, sessions, ledger, audit, account, db
):
    """Three missed ticks and nobody is on the other end.

    Holding the agent open costs real money to talk to an empty room, which is
    why there is no reconnect window (Part 2, Detection). No refund is owed
    either: ticks are charged in arrears, so the time after the last one was
    never billed — the ledger is already correct, and a refund here would be
    handing back minutes the user actually spent.
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
    # One tick landed, and then the phone went into a tunnel.
    await ledger.charge_tick(
        user_id=account.user_id, session_id=session.id, tick_index=0, seconds=15
    )
    await sessions.record_progress(session_id=session.id)
    await _stall(db, session, seconds=120)

    await reaper.reap()

    closed = await sessions.get(session_id=session.id)
    assert closed.state is SessionState.SETTLED
    assert closed.end_reason is EndReason.CLIENT_DISCONNECT
    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == 585
    assert not [
        entry
        for entry in await ledger.entries(user_id=account.user_id)
        if entry.reason is not EntryReason.GRANT_ALLOWANCE
        and entry.reason is not EntryReason.TICK
    ]

    # And the lock is back, in the same sweep — a user whose train went through
    # a tunnel should not wait for a second pass to start again.
    await sessions.start(user_id=account.user_id)


async def test_a_user_who_gets_there_first_does_not_take_the_sweep_down_with_them(
    reaper, sessions, audit, ledger, funded_account, db, monkeypatch
):
    """A sweep is a batch, and one contended session must not end it.

    The reaper selects, then acts, and a user can end their own session in
    between — the session it is holding is already gone by the time it reaches
    it. Letting that escape would abandon every session later in the batch,
    which is the failure that compounds: the ones left behind are still stuck,
    still holding locks, and the next sweep hits the same contention.

    The audit row must not survive the attempt either. It is staged before the
    change it explains so the two commit together; a reaping that never happened
    leaving a row saying it did would make the trail worse than no trail.
    """
    # Funded like any real account: a room cannot open without minutes.
    other = await create_funded_account(db, ledger)
    # Read once, up front. The sweep rolls back when it loses the race below,
    # and a rollback expires every ORM object on this session — these fixtures
    # included. Touching one afterwards reloads it lazily, mid-test.
    owner, other_owner = funded_account.user_id, other.user_id

    contended = await sessions.start(user_id=owner)
    await sessions.activate(session_id=contended.id)
    reapable = await sessions.start(user_id=other_owner)
    await sessions.activate(session_id=reapable.id)
    for session in (contended, reapable):
        await _stall(db, session, seconds=120)

    # The user's own End request lands first, so the transition the reaper is
    # about to attempt is no longer legal.
    original = SessionService.begin_finalizing
    contended_id, reapable_id = contended.id, reapable.id

    async def lost_the_race(self, *, session_id, end_reason):
        if session_id == contended_id:
            raise InvalidStateTransition(
                session_id=str(session_id), from_state="finalizing", to_state="finalizing"
            )
        return await original(self, session_id=session_id, end_reason=end_reason)

    monkeypatch.setattr(SessionService, "begin_finalizing", lost_the_race)

    await reaper.reap()
    monkeypatch.undo()

    assert (await sessions.get(session_id=reapable_id)).state is SessionState.SETTLED
    assert not [
        event
        for event in await audit.events_for_user(user_id=owner)
        if event.event_type is AuditEventType.SESSION_REAPED
    ]
