"""Hearing a room again.

Playback plays the stored object. ElevenLabs is never called and no credits are
consumed — re-synthesising a room costs about a hundred times what storing it
does, and could not reproduce the user's own voice at any price
(`docs/session-retention.md`).

What this file is mostly about is the *third* state. A room whose audio has
expired is not an error and not a missing resource: it is the ordinary
condition of every free-tier room after thirty days, and the client has to be
able to say so in words that are true.
"""

from __future__ import annotations

import pytest

from app.modules.sessions.schemas import RecordingState

from datetime import timedelta

from sqlalchemy import func, update

from app.modules.sessions.models import Session as SessionModel
from app.modules.sessions.retention import RecordingRetention
from app.modules.sessions.schemas import SessionState
from app.modules.sessions.service import SessionService
from app.core.errors import FlintroomError
from app.modules.sessions.router import play_recording
from app.modules.voice.dependencies import get_room_recordings
from app.modules.voice.recording import RoomRecordings

pytestmark = pytest.mark.asyncio


async def _settled_days_ago(db, session_id, *, days: int) -> None:
    """Age a room, using the database's clock rather than Python's.

    The sweep compares `settled_at` against `now()` inside the query, so a
    timestamp written from here would be comparing two machines' clocks — the
    same trap `db_now` exists to avoid.
    """
    await db.execute(
        update(SessionModel)
        .where(SessionModel.id == session_id)
        # Both, because `ck_sessions_settled_at` enforces that settled and
        # timestamped are the same fact — a room with one and not the other is a
        # state the database refuses to hold, and rightly.
        .values(
            state=SessionState.SETTLED,
            settled_at=func.now() - timedelta(days=days),
        )
    )
    await db.commit()



async def test_the_dependency_hands_save_a_database(
    db, sessions, storage, funded_account
):
    """`get_room_recordings` must build a `RoomRecordings` that puts the row on
    the books, not just the object in the bucket.

    Every other test in the suite constructs `RoomRecordings(storage, db=db)`
    by hand, which is exactly how the one call site that matters — the
    production dependency — shipped without a database and nothing went red.
    Found in prod on 2026-09-02: twenty settled rooms, objects in storage,
    zero `session_recordings` rows. No row means no play button, and worse, a
    retention sweep that cannot see audio it is supposed to expire.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await db.commit()

    class _App:
        class state:
            object_storage = storage

    class _Connection:
        app = _App

    built = get_room_recordings(_Connection(), db)
    assert built is not None
    await built.save(session_id=session.id, pcm=b"\x10\x00" * 16_000)

    recording = await SessionService(db).recording(session_id=session.id)
    assert recording.state is RecordingState.AVAILABLE


async def test_a_room_with_audio_reports_that_it_can_be_played(
    db, sessions, storage, funded_account, recordings
):
    session = await sessions.start(user_id=funded_account.user_id)
    await db.commit()
    await RoomRecordings(storage, db=db).save(
        session_id=session.id, pcm=b"\x10\x00" * 16_000
    )

    recording = await SessionService(db).recording(session_id=session.id)

    assert recording.state is RecordingState.AVAILABLE
    assert recording.expires_at is not None


async def test_a_room_that_was_never_recorded_says_so_rather_than_expired(
    db, sessions, funded_account
):
    """The distinction the client needs and a nullable URL cannot carry.

    "This room was not recorded" and "the audio is no longer available" are
    different sentences, and only one of them is the user's own retention
    window arriving on schedule. Collapsing them means telling somebody their
    recording expired when saving was simply off — which reads as data loss.
    """
    session = await sessions.start(user_id=funded_account.user_id)

    recording = await SessionService(db).recording(session_id=session.id)

    assert recording.state is RecordingState.NOT_RECORDED
    assert recording.expires_at is None


async def test_an_expired_room_is_expired_rather_than_absent(
    db, sessions, storage, funded_account
):
    """The normal state of a free room on day thirty-one.

    The row outlives the object precisely so this can be answered. Without it
    an expired room is indistinguishable from one that never recorded, and the
    evidence that a published window was honoured would be gone too.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await db.commit()
    await RoomRecordings(storage, db=db).save(
        session_id=session.id, pcm=b"\x10\x00" * 16_000
    )
    await _settled_days_ago(db, session.id, days=31)
    await RecordingRetention(db, storage).sweep()

    recording = await SessionService(db).recording(session_id=session.id)

    assert recording.state is RecordingState.EXPIRED


async def test_pressing_play_gets_a_url_for_that_room_and_no_other(
    db, sessions, storage, funded_account
):
    """The URL is minted here, not carried on the session.

    A presigned link lives fifteen minutes; a session object can sit in a list
    for far longer. Minting on demand is what keeps every link that reaches a
    player a working one.

    `core/storage.py` is explicit that whether a caller may read a key is the
    service's question, answered *before* it asks for a URL — signing is not a
    permission check, and this layer signs whatever it is told to.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await db.commit()
    await RoomRecordings(storage, db=db).save(
        session_id=session.id, pcm=b"\x10\x00" * 16_000
    )

    playback = await play_recording(
        session=await sessions.get(session_id=session.id),
        sessions=SessionService(db),
        storage=storage,
    )

    assert str(session.id) in playback.url
    assert playback.expires_in_seconds > 0


async def test_a_room_with_nothing_to_play_refuses_rather_than_signing_nothing(
    db, sessions, storage, funded_account
):
    """A URL to an absent object is worse than a refusal.

    It is a link that reaches the store, gets a 403 or a 404 there, and leaves
    the client to interpret somebody else's error page. The state is already
    published on the session, so this is a case a well-behaved client never
    reaches — which is exactly why it must not be a 500 when a badly-behaved
    one does.
    """
    session = await sessions.start(user_id=funded_account.user_id)

    with pytest.raises(FlintroomError) as refusal:
        await play_recording(
            session=await sessions.get(session_id=session.id),
            sessions=SessionService(db),
            storage=storage,
        )

    assert refusal.value.status_code == 404
