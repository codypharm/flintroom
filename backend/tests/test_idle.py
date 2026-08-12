"""Idle detection — the abandoned room.

The expensive failure this exists to catch is a panel monologuing to nobody, so
*panel* speech deliberately does not count as activity (docs Part 2, Detection).
Only the user going quiet matters, and a room nobody has ever spoken in counts
as quiet from the moment it opened.

Unlike the session cap, this one pays money back: the user did not receive the
time, so they are not charged for it.
"""

from datetime import timedelta

from sqlalchemy import func, update

from app.modules.billing.schemas import Bucket, EntryReason
from app.modules.sessions.models import Session as SessionModel
from app.modules.sessions.models import SessionPhaseSpan
from app.modules.sessions.schemas import EndReason, SessionState


async def _quiet_for(db, session, *, seconds: int) -> None:
    """Age the room without anyone speaking in it.

    Backdating the span is what makes this a room that has been open and silent
    the whole time — which is the case the answer to "never spoke" resolved:
    the clock runs from the span, not from a first word that never came.
    """
    await db.execute(
        update(SessionPhaseSpan)
        .where(
            SessionPhaseSpan.session_id == session.id,
            SessionPhaseSpan.ended_at.is_(None),
        )
        .values(started_at=func.now() - timedelta(seconds=seconds))
    )
    await db.commit()


async def test_the_silent_window_is_refunded_and_the_rest_is_not(
    meter, sessions, ledger, account, db
):
    """They pay for the room they were in, not the one they walked away from.

    Arrears already means nothing is charged before it is served, so this is the
    one case where money has to come back: the seconds *were* served, and the
    user was not there to receive them. Refunding the whole session instead
    would hand back a rehearsal that worked perfectly right up until they left.

    Bucket-faithful, because allowance expires at the period boundary and top-up
    never does — returning the right number of seconds to the wrong bucket is a
    refund that quietly evaporates.
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
    await _quiet_for(db, session, seconds=180)
    # They spoke 65 seconds in, then stopped. 115 seconds of silence.
    await db.execute(
        update(SessionModel)
        .where(SessionModel.id == session.id)
        .values(last_user_speech_at=func.now() - timedelta(seconds=115))
    )
    await db.commit()

    await meter.sweep()

    # 180s ran and was charged. The refund is 120s, not 115: the tick covering
    # 60-75s straddles the moment they went quiet, and a straddling tick is
    # returned whole rather than split — rounded the user's way, like every
    # other rounding in the ledger.
    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == 540
    refunds = [
        entry
        for entry in await ledger.entries(user_id=account.user_id)
        if entry.reason is EntryReason.REFUND_IDLE
    ]
    assert [(entry.bucket, entry.delta_seconds) for entry in refunds] == [
        (Bucket.ALLOWANCE, 120)
    ]


async def test_an_abandoned_room_reads_as_idle_even_past_the_session_cap(
    meter, sessions, ledger, account, db
):
    """When both endings apply, the one that happened first is the true one.

    This is not bookkeeping pedantry: the end reason decides whether the user is
    refunded. A room abandoned after ninety seconds and closed twelve minutes
    later — because the sweep was down in between — is a user who was not there
    for eleven of those minutes. Recording it as `session_cap` says they used
    their full session and refunds them nothing.
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=3600,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await _quiet_for(db, session, seconds=12 * 60 + 15)

    await meter.sweep()

    assert (
        await sessions.get(session_id=session.id)
    ).end_reason is EndReason.IDLE_TIMEOUT


async def test_speaking_resets_the_silence(meter, sessions, ledger, account, db):
    """A room that has been open a long time is not the same as an idle one.

    This is the distinction the whole feature turns on. Without it, idle
    detection is just a second session cap with a shorter fuse, and it would
    close on the most engaged user in the product — the one still going at two
    minutes because the panel keeps coming back at them.
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
    await _quiet_for(db, session, seconds=120)

    # They have been arguing back the whole time; the voice layer says so.
    await sessions.record_speech(session_id=session.id)

    await meter.sweep()

    assert (await sessions.get(session_id=session.id)).state is SessionState.ACTIVE


async def test_a_user_taking_time_to_think_is_not_cut_off(
    meter, sessions, ledger, account, db
):
    """A pause is the product working, not a fault.

    The whole premise is a hostile question the user has to think about. A
    cutoff short enough to punish thinking would train exactly the reflexive
    answering the room exists to break — so the boundary has to mean something,
    and it has to sit well past a long silence.
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
    await _quiet_for(db, session, seconds=60)

    await meter.sweep()

    assert (await sessions.get(session_id=session.id)).state is SessionState.ACTIVE


async def test_a_room_nobody_is_speaking_in_is_closed(
    meter, sessions, ledger, account, db
):
    """The tracer: silence long enough is an abandoned room.

    Nothing in the balance would ever stop this user — they have minutes — so
    without idle detection the room runs until the twelve-minute cap, with the
    voice provider billing us for every second of an empty room.
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
    await _quiet_for(db, session, seconds=120)

    await meter.sweep()

    closed = await sessions.get(session_id=session.id)
    assert closed.state is SessionState.SETTLED
    assert closed.end_reason is EndReason.IDLE_TIMEOUT
