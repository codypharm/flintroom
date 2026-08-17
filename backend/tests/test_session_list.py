"""The rooms an account still has.

Settings leads with what Flintroom holds — how many rooms, and when the oldest
stops being playable — and `/v1/sessions` was POST-only, so nothing could answer
it. The library surface needs the same list.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.sessions.schemas import EndReason, RecordingState
from app.modules.sessions.service import SessionService
from app.modules.voice.recording import RoomRecordings

pytestmark = pytest.mark.asyncio


async def test_a_new_account_holds_nothing(db, funded_account):
    """The empty state is most people's first sight of Settings.

    It has to be a fact rather than an absence — an endpoint that 404s or errors
    on "no rooms yet" turns the ordinary first launch into an error screen.
    """
    assert await SessionService(db).recent(user_id=funded_account.user_id) == []


async def test_it_lists_the_room_and_whether_it_can_still_be_heard(
    db, sessions, storage, funded_account
):
    session = await sessions.start(user_id=funded_account.user_id)
    await db.commit()
    await RoomRecordings(storage, db=db).save(
        session_id=session.id, pcm=b"\x10\x00" * 16_000
    )

    rooms = await SessionService(db).recent(user_id=funded_account.user_id)

    assert [room.id for room in rooms] == [session.id]
    assert rooms[0].recording.state is RecordingState.AVAILABLE
    assert rooms[0].recording.expires_at is not None


async def test_it_shows_the_newest_room_first(
    db, sessions, settlement, funded_account
):
    """A list of rehearsals is read newest-first — the one just finished is the
    one somebody came to find.

    The first room has to be closed before the second exists: one live session
    per user is enforced by a partial unique index, not by a check that could be
    skipped in a test.
    """
    first = await sessions.start(user_id=funded_account.user_id)
    await sessions.activate(session_id=first.id)
    await settlement.close(
        session_id=first.id, end_reason=EndReason.CLIENT_DISCONNECT
    )
    second = await sessions.start(user_id=funded_account.user_id)

    rooms = await SessionService(db).recent(user_id=funded_account.user_id)

    assert [room.id for room in rooms] == [second.id, first.id]


async def test_it_never_shows_somebody_else_their_rooms(db, sessions, funded_account):
    """Ownership is a filter here rather than a check afterwards.

    `OwnedSession` guards the single-session routes, but a list has no id to
    check against — so the scope lives in the query, where forgetting it is a
    disclosure rather than a 403.
    """
    await sessions.start(user_id=funded_account.user_id)

    assert await SessionService(db).recent(user_id=uuid.uuid4()) == []
