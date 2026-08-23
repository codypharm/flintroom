"""The reconnect window — a dropped room's way back. docs/reconnect.md.

The exhibit behind all of this: a phone died mid-sentence, the relay settled
the room within a second, and there was no way back. These tests hold the
resolved design: the room stays `active` under a `disconnected_at` stamp, its
interrogation span closes so nothing bills while nobody is there, a fresh
connection resumes it by opening a new span, and the reaper gives up on its
behalf once the stamp outlives the window.
"""

import uuid
from datetime import timedelta

from sqlalchemy import func, select, update

from app.modules.billing.schemas import Bucket, EntryReason
from app.modules.sessions.models import Session as SessionModel
from app.modules.sessions.models import SessionPhaseSpan
from app.modules.sessions.schemas import (
    RECONNECT_WINDOW,
    EndReason,
    SessionState,
)

from .conftest import mark_heard


async def _grant(ledger, account, seconds: int = 600) -> None:
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=seconds,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )


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


async def _dropped_for(db, session, *, seconds: int) -> None:
    """Backdate the disconnect stamp, leaving everything else alone."""
    await db.execute(
        update(SessionModel)
        .where(SessionModel.id == session.id)
        .values(disconnected_at=func.now() - timedelta(seconds=seconds))
    )
    await db.commit()


async def _open_spans(db, session) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(SessionPhaseSpan)
        .where(
            SessionPhaseSpan.session_id == session.id,
            SessionPhaseSpan.ended_at.is_(None),
        )
    )
    return int(result.scalar_one())


async def test_a_dropped_connection_stamps_the_room_and_closes_its_window(
    sessions, ledger, account, db
):
    """The room neither settles nor keeps billing: it waits.

    Closing the span is the whole trick — the meter joins on an open span, so
    one write suspends billing, the caps and the idle clock together, and
    settlement's span sum will never contain the tunnel.
    """
    await _grant(ledger, account)
    socket = uuid.uuid4()
    session = await sessions.start(user_id=account.user_id)
    await sessions.connection_opened(session_id=session.id, connection_id=socket)

    await sessions.connection_lost(session_id=session.id, connection_id=socket)

    waiting = await sessions.get(session_id=session.id)
    assert waiting.state is SessionState.ACTIVE
    assert waiting.disconnected_at is not None
    assert await _open_spans(db, session) == 0


async def test_a_stale_socket_cannot_stamp_a_room_it_no_longer_speaks_for(
    sessions, ledger, account, db
):
    """The half-open case. A phone loses network, reconnects fast, and the
    dead socket's relay only notices later — its dying write must not stop
    the billing of a room whose presenter is mid-answer."""
    await _grant(ledger, account)
    stale, current = uuid.uuid4(), uuid.uuid4()
    session = await sessions.start(user_id=account.user_id)
    await sessions.connection_opened(session_id=session.id, connection_id=stale)
    # The reconnect arrives before the old socket dies: supersede.
    await sessions.connection_opened(session_id=session.id, connection_id=current)

    await sessions.connection_lost(session_id=session.id, connection_id=stale)

    live = await sessions.get(session_id=session.id)
    assert live.disconnected_at is None
    assert await _open_spans(db, session) == 1


async def test_resuming_clears_the_stamp_and_opens_a_new_window(
    sessions, ledger, account, db
):
    await _grant(ledger, account)
    first, second = uuid.uuid4(), uuid.uuid4()
    session = await sessions.start(user_id=account.user_id)
    await sessions.connection_opened(session_id=session.id, connection_id=first)
    await sessions.connection_lost(session_id=session.id, connection_id=first)

    await sessions.connection_opened(session_id=session.id, connection_id=second)

    resumed = await sessions.get(session_id=session.id)
    assert resumed.state is SessionState.ACTIVE
    assert resumed.disconnected_at is None
    assert await _open_spans(db, session) == 1


async def test_the_meter_does_not_bill_a_room_in_its_reconnect_window(
    meter, sessions, ledger, account, db
):
    """Decision 2: the window is unbilled. Nobody is interrogated in a
    tunnel, and charging for it would be billing dead air."""
    await _grant(ledger, account)
    socket = uuid.uuid4()
    session = await sessions.start(user_id=account.user_id)
    await sessions.connection_opened(session_id=session.id, connection_id=socket)
    await _running_for(db, session, seconds=60)
    await meter.sweep()
    charged = (await ledger.balance(user_id=account.user_id)).total_seconds

    await sessions.connection_lost(session_id=session.id, connection_id=socket)
    await meter.sweep()

    assert (await ledger.balance(user_id=account.user_id)).total_seconds == charged


async def test_resumed_ticks_continue_where_they_left_off(
    meter, sessions, ledger, account, db
):
    """The ledger's `(session_id, tick_index)` idempotency carries straight
    across the gap: the index is derived from the *sum* of span seconds, so
    the tunnel never enters the arithmetic and no tick is skipped or paid
    twice."""
    await _grant(ledger, account)
    first, second = uuid.uuid4(), uuid.uuid4()
    session = await sessions.start(user_id=account.user_id)
    await sessions.connection_opened(session_id=session.id, connection_id=first)
    await _running_for(db, session, seconds=60)
    await meter.sweep()
    assert (await ledger.balance(user_id=account.user_id)).total_seconds == 540

    await sessions.connection_lost(session_id=session.id, connection_id=first)
    await sessions.connection_opened(session_id=session.id, connection_id=second)
    await _running_for(db, session, seconds=30)
    await meter.sweep()

    # 60 consumed before the drop, 30 after: six ticks, 90 seconds — however
    # long the tunnel between them lasted.
    assert (await ledger.balance(user_id=account.user_id)).total_seconds == 510


async def test_the_reaper_settles_a_room_whose_window_ran_out(
    reaper, sessions, ledger, account, db
):
    """Thirty seconds of hope, then the same ending the relay used to write
    immediately. The stamp is the only clock consulted — `last_progress_at`
    stays fresh here so the orphan path cannot be what closed it."""
    await _grant(ledger, account)
    socket = uuid.uuid4()
    session = await sessions.start(user_id=account.user_id)
    await sessions.connection_opened(session_id=session.id, connection_id=socket)
    await mark_heard(db, session.id)
    await sessions.connection_lost(session_id=session.id, connection_id=socket)
    await _dropped_for(
        db, session, seconds=int(RECONNECT_WINDOW.total_seconds()) + 10
    )

    await reaper.reap()

    closed = await sessions.get(session_id=session.id)
    assert closed.state is SessionState.SETTLED
    assert closed.end_reason is EndReason.CLIENT_DISCONNECT


async def test_a_room_still_inside_its_window_is_left_alone(
    reaper, sessions, ledger, account, db
):
    await _grant(ledger, account)
    socket = uuid.uuid4()
    session = await sessions.start(user_id=account.user_id)
    await sessions.connection_opened(session_id=session.id, connection_id=socket)
    await sessions.connection_lost(session_id=session.id, connection_id=socket)
    await _dropped_for(
        db, session, seconds=int(RECONNECT_WINDOW.total_seconds()) - 10
    )

    await reaper.reap()

    waiting = await sessions.get(session_id=session.id)
    assert waiting.state is SessionState.ACTIVE


async def test_a_resumed_room_is_not_instantly_idle(
    meter, sessions, ledger, account, db
):
    """Idle is suspended by the closed span and re-based by the new one.

    The presenter last spoke before the drop. If quiet-time were measured
    from that mark alone, a resume after a long-enough gap would be reaped
    as idle on the next sweep — the window made a lie. Measuring from the
    newer of last-speech and the current span's start gives the returning
    presenter the full idle allowance without fabricating a speech
    timestamp."""
    await _grant(ledger, account)
    first, second = uuid.uuid4(), uuid.uuid4()
    session = await sessions.start(user_id=account.user_id)
    await sessions.connection_opened(session_id=session.id, connection_id=first)
    await _running_for(db, session, seconds=60)
    # They spoke early, then the line dropped: last speech is now stale
    # enough that the old arithmetic would call the room abandoned.
    await db.execute(
        update(SessionModel)
        .where(SessionModel.id == session.id)
        .values(last_user_speech_at=func.now() - timedelta(seconds=120))
    )
    await db.commit()
    await sessions.connection_lost(session_id=session.id, connection_id=first)
    await sessions.connection_opened(session_id=session.id, connection_id=second)

    await meter.sweep()

    resumed = await sessions.get(session_id=session.id)
    assert resumed.state is SessionState.ACTIVE
