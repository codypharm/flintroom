"""Grace overdraft and its forgiveness.

Product.md §4.5 forbids interrupting a live interrogation, so a session whose
balance hits zero keeps running on a bounded grace overdraft. The write-off is
recorded as a typed entry rather than by zeroing the balance — replaying the log
has to reproduce the cached balance, which is the whole reason the ledger is
append-only.
"""

import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, update

from app.core.errors import SessionNotLive
from app.modules.billing.schemas import Bucket, EntryReason
from app.modules.sessions.models import Session as SessionModel
from app.modules.sessions.schemas import EndReason, SessionState



async def _in_grace_for(db, session, *, seconds: int) -> None:
    """Backdate the grace clock, without touching anything else.

    The cap is computed by Postgres from a timestamp Postgres wrote, so Postgres
    is the only clock in the comparison — moving Python's would prove nothing
    about it.
    """
    await db.execute(
        update(SessionModel)
        .where(SessionModel.id == session.id)
        .values(grace_started_at=func.now() - timedelta(seconds=seconds))
    )
    await db.commit()


async def test_running_out_mid_room_starts_the_clock_without_stopping_the_room(
    sessions, ledger, account
):
    """The tracer: hitting zero is not an ending.

    §4.5 forbids interrupting a live interrogation, and this is the moment that
    rule is actually load-bearing — the panel is mid-question and the user has
    just run out. The room keeps going; what changes is that a clock starts, so
    "never cut them off" cannot mean "runs free forever".
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=10,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)

    balance = await ledger.charge_tick(
        user_id=account.user_id, session_id=session.id, tick_index=0, seconds=15
    )
    assert balance.total_seconds == -5

    capped = await sessions.enter_grace(session_id=session.id)

    assert capped is False
    assert (await sessions.get(session_id=session.id)).state is SessionState.ACTIVE


async def test_a_room_still_overdrawing_past_the_cap_is_told_to_close(
    sessions, ledger, account, db
):
    """"Never cut them off" cannot mean "runs free forever".

    Grace is bounded because every second of it is a real invoice from the voice
    provider against a user who is not paying for it (docs Part 1, Zero
    mid-session). The cap is what makes the write-off a known, small number
    instead of whatever an abandoned room costs by morning.
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=10,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await ledger.charge_tick(
        user_id=account.user_id, session_id=session.id, tick_index=0, seconds=15
    )
    await sessions.enter_grace(session_id=session.id)

    # ...and it kept going, tick after tick, well past the cap.
    await _in_grace_for(db, session, seconds=180)

    assert await sessions.enter_grace(session_id=session.id) is True


async def test_grace_cannot_start_on_a_room_that_is_no_longer_live(
    sessions, ledger, funded_account
):
    """A tick in flight when the room closed must not restart the clock.

    The meter selects live rooms and then acts on them, and in between the user
    can press End or the reaper can close an orphan. Stamping grace on a session
    that is already settling would hand a closed room a fresh two minutes, and
    the next sweep would find a clock running on something nobody is in.

    A refusal rather than a silent no-op, because the caller needs to hear it:
    the honest response to "this room is gone" is to stop ticking it.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await sessions.activate(session_id=session.id)
    await sessions.begin_finalizing(
        session_id=session.id, end_reason=EndReason.USER_ENDED
    )

    with pytest.raises(SessionNotLive):
        await sessions.enter_grace(session_id=session.id)


async def test_leaving_grace_refuses_on_a_closed_room_too(sessions, funded_account):
    """Both branches of the tick answer the same way to a room that is gone.

    The meter enters grace on an overdrawn tick and leaves it on a healthy one.
    If only one of those refuses, whether a lost race is survivable depends on
    the user's balance at that moment — which is the kind of asymmetry that
    produces a bug reproducible only when someone is nearly out of minutes.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await sessions.activate(session_id=session.id)
    await sessions.begin_finalizing(
        session_id=session.id, end_reason=EndReason.USER_ENDED
    )

    with pytest.raises(SessionNotLive):
        await sessions.leave_grace(session_id=session.id)


async def test_topping_up_mid_room_earns_a_fresh_grace_window(
    sessions, ledger, account, db
):
    """Someone who just paid us must not be cut off in the same breath.

    Grace measures the *current* overdraft, not a per-session ration. A user who
    tops up mid-interrogation is back in the black, and if they later run dry
    again they are entitled to the same two minutes as anyone else — carrying
    the old clock forward would end the room the instant the new minutes ran
    out, which is the worst possible moment to have taken their money.
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=10,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await ledger.charge_tick(
        user_id=account.user_id, session_id=session.id, tick_index=0, seconds=15
    )
    await sessions.enter_grace(session_id=session.id)
    # Long enough that a carried-over clock would close the room immediately.
    await _in_grace_for(db, session, seconds=180)

    # They buy minutes without leaving the room.
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.TOPUP,
        seconds=600,
        reason=EntryReason.GRANT_TOPUP,
        idempotency_key="topup-1",
    )
    balance = await ledger.charge_tick(
        user_id=account.user_id, session_id=session.id, tick_index=1, seconds=15
    )
    assert balance.total_seconds > 0
    await sessions.leave_grace(session_id=session.id)

    # Much later, the top-up runs out too. That is a new overdraft.
    assert await sessions.enter_grace(session_id=session.id) is False


async def test_forgiving_an_overdraft_clears_it_and_records_why(ledger, account):
    """The write-off is an entry, and it is typed as forgiveness.

    Silently resetting the balance to zero would leave the entry history and the
    cached balance permanently disagreeing, which is exactly the drift the
    append-only model exists to make impossible.
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=10,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )
    session_id = uuid.uuid4()

    # The panel is mid-question; §4.5 says it finishes. This runs 20s past zero.
    overdrawn = await ledger.charge_tick(
        user_id=account.user_id, session_id=session_id, tick_index=0, seconds=30
    )
    assert overdrawn.allowance_seconds == -20

    balance = await ledger.forgive_overdraft(user_id=account.user_id, session_id=session_id)

    assert balance.allowance_seconds == 0

    entries = await ledger.entries(user_id=account.user_id)
    forgiven = [e for e in entries if e.reason is EntryReason.GRACE_FORGIVEN]
    assert [(e.bucket, e.delta_seconds) for e in forgiven] == [(Bucket.ALLOWANCE, 20)]


async def test_forgiving_twice_does_not_hand_out_minutes(ledger, account):
    """Settlement is retried, so forgiveness must be idempotent.

    `finalizing` exists precisely so a crashed settle can be retried, and the
    reaper does retry it. A second forgiveness would credit the overdraft again
    and leave the account with free minutes it never bought.
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=10,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )
    session_id = uuid.uuid4()
    await ledger.charge_tick(
        user_id=account.user_id, session_id=session_id, tick_index=0, seconds=30
    )

    await ledger.forgive_overdraft(user_id=account.user_id, session_id=session_id)
    balance = await ledger.forgive_overdraft(user_id=account.user_id, session_id=session_id)

    assert balance.allowance_seconds == 0
    forgiven = [
        e for e in await ledger.entries(user_id=account.user_id)
        if e.reason is EntryReason.GRACE_FORGIVEN
    ]
    assert len(forgiven) == 1
