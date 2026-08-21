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


async def test_a_listed_room_says_who_was_in_it(db, sessions, funded_account):
    """#94, and the Library was making a false statement about somebody's history.

    `recent()` populated `recording` and `rehearsal_name` and nothing else, so
    every other field fell to its default — and `archetypes` defaults to the
    empty list. Every row in the Library therefore read as a room nobody sat in,
    against a database where all 62 of the architect's sessions had a full panel.

    The single read has always been right, which is what made this invisible:
    `_read` in the router assembles the same schema and does populate it. Two
    paths, one shape, and only one of them filled it in.
    """
    session = await sessions.start(
        user_id=funded_account.user_id,
        archetypes=["technical_skeptic", "champion", "cfo"],
    )
    await db.commit()

    (room,) = await SessionService(db).recent(user_id=funded_account.user_id)

    # In seat order, because that is what "Run it again" re-seats from and
    # `routing.choose` breaks a scoring tie on the panel's own index.
    assert room.archetypes == ["technical_skeptic", "champion", "cfo"]


async def test_a_listed_room_says_what_it_was_grounded_in(
    db, sessions, ingestion, storage, funded_account
):
    """The same hole, one field over, and it costs more than it looks.

    "Run it again" carries `material` from the Library row into the setup
    screen. Empty, it re-runs a grounded rehearsal with no deck — a different
    room than the one it names, and the panel loses the claims it was quoting.
    """
    from tests.materials import extracted

    # Through the real path: a room refuses material that has not been read
    # (`MaterialNotReady`), so a half-registered one could never be attached and
    # would not exercise this at all.
    material = await extracted(db, ingestion, storage, funded_account)
    session = await sessions.start(
        user_id=funded_account.user_id, material_ids=[material.id]
    )
    await db.commit()

    (room,) = await SessionService(db).recent(user_id=funded_account.user_id)

    assert room.material_ids == [material.id]


async def test_the_list_and_the_single_read_agree_about_a_room(
    db, client, bearer, sessions, funded_account
):
    """Two paths assembling one schema is how they drift, so this pins them.

    The whole class of bug: `SessionRead` has defaults for every field the list
    forgot, so forgetting one is silent — no error, no empty response, just a
    plausible room with nobody in it.
    """
    session = await sessions.start(
        user_id=funded_account.user_id, archetypes=["cfo", "champion"]
    )
    await db.commit()

    listed = (
        await client.get("/v1/sessions", headers=bearer(funded_account.user_id))
    ).json()
    alone = (
        await client.get(
            f"/v1/sessions/{session.id}", headers=bearer(funded_account.user_id)
        )
    ).json()

    assert listed[0]["archetypes"] == alone["archetypes"] == ["cfo", "champion"]
    assert listed[0]["material_ids"] == alone["material_ids"]
