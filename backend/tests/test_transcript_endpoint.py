"""Reading a room back, over HTTP.

The transcript has been persisted since #47 and kept for the life of the account
ever since — `docs/session-retention.md` gives it a longer window than the audio
precisely because text is tens of kilobytes and does not compound. Nothing has
ever served it to a client. The Library gave that a reason: the architect's own
definition of it is *"a browser for all past sessions in case you want to view
the detail of discussion or play it and listen to it"*, and the first half of
that had no backend at all.

**Why this is allowed to exist at all**, since a transcript is the most private
thing this product holds. `CLAUDE.md` bans a transcript from a *list* endpoint,
which is exactly the carve-out shape: one room, named in the path, behind
`OwnedSession`. Nothing here widens what is kept, how long it is kept, or who
may read it — it lets the person who said it read their own words back.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.context import USER, Said
from app.modules.sessions.schemas import EndReason
from app.modules.sessions.transcript import SessionTranscript

from tests.conftest import create_funded_account
from tests.test_debrief import room_that_happened

ROOM = (
    Said(speaker=USER, text="We grew forty percent last quarter."),
    Said(speaker="cfo", text="Off what base, and at what cost?"),
    Said(speaker=USER, text="We are really pleased with the trajectory."),
)


async def test_a_room_reads_back_in_the_order_it_happened(
    client, db, engine, sessions, settlement, funded_account, bearer
):
    """The tracer, and the ordering is the content rather than the presentation.

    `TranscriptLine.ordinal` exists because lines are written as they are said,
    so two can share a clock reading — and the same lines rearranged describe a
    room that did not happen.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )

    response = await client.get(
        f"/v1/sessions/{session.id}/transcript",
        headers=bearer(funded_account.user_id),
    )

    assert response.status_code == 200
    said = response.json()["lines"]
    assert [line["text"] for line in said] == [line.text for line in ROOM]
    assert [line["ordinal"] for line in said] == [0, 1, 2]


async def test_it_says_who_spoke_without_deciding_what_to_call_them(
    client, db, engine, sessions, settlement, funded_account, bearer
):
    """Archetype names, not rendered titles.

    The same identity used in logs, in routing and in the room's own transcript.
    The client resolves them against the archetype catalogue it already reads to
    offer the picker — and a second spelling of "The CFO" on the wire is how two
    surfaces come to disagree about what somebody is called.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )

    response = await client.get(
        f"/v1/sessions/{session.id}/transcript",
        headers=bearer(funded_account.user_id),
    )

    assert [line["speaker"] for line in response.json()["lines"]] == [
        "user",
        "cfo",
        "user",
    ]


async def test_it_carries_when_each_line_was_written(
    client, db, engine, sessions, settlement, funded_account, bearer
):
    """Enough to orient a reader. Not enough to anchor playback, and #69 is why.

    `said_at` defaults to `now()` at insert, so it is when the line was *written*
    rather than when the audio was heard. Lines are written as they are said, so
    it is close — but "close" is the difference between a reading aid and a
    playback offset, and #69 exists because there is no true offset anywhere.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )

    response = await client.get(
        f"/v1/sessions/{session.id}/transcript",
        headers=bearer(funded_account.user_id),
    )

    assert all(line["said_at"] for line in response.json()["lines"])


async def test_one_user_cannot_read_another_users_room(
    client, db, engine, sessions, settlement, funded_account, bearer, ledger
):
    """The most private thing the product holds, so this is the test that matters.

    404 rather than 403, like every other owned session: a 403 confirms the room
    exists, which turns the endpoint into an oracle for guessing ids, and a
    caller who does not own it has the same next move either way.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    stranger = await create_funded_account(db, ledger)

    response = await client.get(
        f"/v1/sessions/{session.id}/transcript", headers=bearer(stranger.user_id)
    )

    assert response.status_code == 404
    # And nothing about the room leaked on the way to refusing.
    assert "grew forty percent" not in response.text


async def test_reading_a_transcript_without_a_credential_reads_nothing(
    client, db, engine, sessions, settlement, funded_account
):
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )

    response = await client.get(f"/v1/sessions/{session.id}/transcript")

    assert response.status_code == 401
    assert "grew forty percent" not in response.text


async def test_a_room_where_nobody_said_anything_reads_back_empty(
    client, db, engine, sessions, settlement, funded_account, bearer
):
    """Empty is a real answer, not a refusal.

    Ordinary and common: a room can end before the panel gets a question out,
    and every session in the dev database so far settled as `client_disconnect`.
    A 404 here would say the room does not exist, which is a different and wrong
    statement — the Library is about to link straight to it.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, ended=EndReason.USER_ENDED
    )

    response = await client.get(
        f"/v1/sessions/{session.id}/transcript",
        headers=bearer(funded_account.user_id),
    )

    assert response.status_code == 200
    assert response.json()["lines"] == []


async def test_a_room_that_never_existed_is_a_404(client, funded_account, bearer):
    """And not a 500 from a service handed a UUID with nothing behind it."""
    response = await client.get(
        "/v1/sessions/00000000-0000-0000-0000-000000000000/transcript",
        headers=bearer(funded_account.user_id),
    )

    assert response.status_code == 404


async def test_it_carries_where_in_the_recording_each_line_began(
    client, db, engine, sessions, settlement, funded_account, bearer
):
    """#69, and the half that makes the column worth writing.

    This screen already sits beside the player — `rooms/[id]` renders the
    transcript and the audio together — so an offset on the line is what turns
    "hear the room again, from the top" into "hear the CFO ask this". Without it
    on the wire the column would be written and never read, which is the shape
    of a field that quietly goes wrong.

    Seconds into the *mixed recording*, not a wall clock. `said_at` beside it is
    when the row was written and says so; nothing should seek with that one.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await sessions.activate(session_id=session.id)
    await db.commit()

    transcript = SessionTranscript(
        async_sessionmaker(engine, expire_on_commit=False), session_id=session.id
    )
    await transcript.record(ROOM[0], at=0.0)
    await transcript.record(ROOM[1], at=14.25)
    await settlement.close(session_id=session.id, end_reason=EndReason.USER_ENDED)

    response = await client.get(
        f"/v1/sessions/{session.id}/transcript",
        headers=bearer(funded_account.user_id),
    )

    assert response.status_code == 200
    assert [line["began_at_seconds"] for line in response.json()["lines"]] == [0.0, 14.25]


async def test_a_room_that_was_never_timed_says_so_rather_than_saying_zero(
    client, db, engine, sessions, settlement, funded_account, bearer
):
    """Null travels as null. Every room recorded before #69 is one of these.

    A client that received `0.0` here would offer to play from the top of the
    room for every line in it — a control that looks like it works and does the
    wrong thing, which is worse than one that is absent because there is nothing
    to anchor to.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )

    response = await client.get(
        f"/v1/sessions/{session.id}/transcript",
        headers=bearer(funded_account.user_id),
    )

    assert response.status_code == 200
    assert all(line["began_at_seconds"] is None for line in response.json()["lines"])
