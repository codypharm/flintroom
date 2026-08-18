"""The ranked list, over HTTP.

`DebriefService` has been exercised directly since #57; this is the first time
anything outside the process can reach it. What these tests add is what the
transport introduces: who is calling, whether they own the room, and what a
refusal looks like on the wire.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from sqlalchemy import update

from app.agents.context import USER, Said
from app.agents.difficulty import GENTLE, RELENTLESS, STANDARD
from app.modules.sessions.models import Session
from app.core.errors import ProviderUnavailable
from app.modules.sessions.dependencies import get_weakness_reader
from app.agents.weakness import Judgement, Weakness
from app.modules.sessions.schemas import EndReason

from tests.conftest import create_funded_account
from tests.test_debrief import ROOM, room_that_happened

ROOM = (
    Said(speaker=USER, text="We grew forty percent last quarter."),
    Said(speaker="cfo", text="Off what base, and at what cost?"),
    Said(speaker=USER, text="We are really pleased with the trajectory."),
)

FOUND = Judgement(
    ordinal=1,
    quote="Off what base, and at what cost?",
    weakness=Weakness.EVASIVE,
    why="You answered with a feeling about the trend, not a base.",
)


async def test_a_debrief_hands_back_what_the_room_got_wrong(
    client, db, engine, sessions, settlement, funded_account, bearer, weakness_reader
):
    """The tracer: a settled room, read once, returned ranked.

    Every field a client needs to render §3.5's artefact is asserted, because
    the prep sheet shows the user their own words back — the question, what they
    said, and the sentence about what was missing. A response carrying only a
    category would be a scorecard, which is the product this one exists to
    refuse.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    weakness_reader.judged = (FOUND,)

    response = await client.get(
        f"/v1/sessions/{session.id}/debrief",
        headers=bearer(funded_account.user_id),
    )

    assert response.status_code == 200
    assert response.json()["weak_answers"] == [
        {
            "ordinal": 1,
            "question": "Off what base, and at what cost?",
            "asked_by": "cfo",
            "answer": "We are really pleased with the trajectory.",
            "weakness": "evasive",
            "why": "You answered with a feeling about the trend, not a base.",
        }
    ]


async def test_somebody_elses_room_is_not_readable(
    client, db, engine, sessions, settlement, funded_account, bearer, ledger,
    weakness_reader,
):
    """A transcript is the most private thing this product holds.

    `docs/session-retention.md` keeps it for the life of the account precisely
    because the debrief needs it, which makes this endpoint the one that hands
    the contents of somebody's rehearsal to whoever asks. Ownership is settled
    before the body runs, and the assertion is that the reader was never called
    — a 403 returned after a model had already read the room would still have
    read the room.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    stranger = await create_funded_account(db, ledger)

    response = await client.get(
        f"/v1/sessions/{session.id}/debrief",
        headers=bearer(stranger.user_id),
    )

    assert response.status_code == 404
    assert weakness_reader.calls == 0


async def test_reading_a_debrief_twice_reads_the_room_once(
    client, db, engine, sessions, settlement, funded_account, bearer, weakness_reader
):
    """Idempotency, asserted where a client will actually hit it.

    A phone that backgrounds and resumes re-fetches. A user who taps back and
    forward re-fetches. Neither should buy a second reasoning-model call, and
    neither should see the list reorder — the ranking moves between runs on the
    same transcript, so a recomputed list would reshuffle under somebody working
    through it.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    weakness_reader.judged = (FOUND,)
    headers = bearer(funded_account.user_id)

    first = await client.get(f"/v1/sessions/{session.id}/debrief", headers=headers)
    second = await client.get(f"/v1/sessions/{session.id}/debrief", headers=headers)

    assert weakness_reader.calls == 1
    assert first.json() == second.json()


async def test_a_room_that_never_existed_is_a_404(client, funded_account, bearer):
    """And not a 500 from a service handed a UUID with nothing behind it."""
    response = await client.get(
        f"/v1/sessions/{uuid.uuid4()}/debrief",
        headers=bearer(funded_account.user_id),
    )

    assert response.status_code == 404


async def test_a_room_the_provider_broke_says_so_on_the_wire(
    client, db, engine, sessions, settlement, funded_account, bearer, weakness_reader
):
    """Decision 7 reaching the client as something it can act on.

    The code matters more than the status here: the app has to offer a fresh
    room rather than an error, and it cannot tell "your minutes are back, start
    again" from "something went wrong" out of a 422 alone.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM,
        ended=EndReason.PROVIDER_FAILURE,
    )

    response = await client.get(
        f"/v1/sessions/{session.id}/debrief",
        headers=bearer(funded_account.user_id),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "room_broke"
    assert weakness_reader.calls == 0


def test_a_deployment_without_a_model_says_so_rather_than_crashing():
    """The guard no request test can reach, because they all substitute a reader.

    `build_weakness_reader` returns `None` without credentials — deliberately,
    so a deployment missing one still signs people in, opens rooms and keeps
    transcripts. That choice moves the failure here, and it has to arrive as a
    typed 502 rather than an `AttributeError` on `None`: one tells the client
    the debrief is unavailable, the other is a stack trace and a 500 on the
    phase §3.5 calls "the part users will pay for".

    Vendor-anonymous, as CLAUDE.md requires. The reason names a capability, not
    a company.
    """
    unconfigured = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    with pytest.raises(ProviderUnavailable) as refused:
        get_weakness_reader(unconfigured)

    assert refused.value.status_code == 502
    assert "gemini" not in str(refused.value.context).lower()


async def test_the_debrief_says_how_this_room_compared_to_the_last(
    client, db, engine, sessions, settlement, funded_account, bearer, weakness_reader
):
    """#55 decision 5, and it is the half the decision called load-bearing.

    Resilience nobody noticed they built is worth nothing — §434 routes the user
    into rebuilding the answer, and a room that quietly got harder is a room
    they cannot credit themselves for having handled.

    A direction, never a number. The client writes the sentence; the API states
    the fact. A level on this screen would turn the debrief into a score, which
    is the drift toward the delivery-metrics product the wedge exists to refuse.
    """
    first = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    await _ran_at(db, first.id, GENTLE)
    second = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    await _ran_at(db, second.id, RELENTLESS)

    body = (
        await client.get(
            f"/v1/sessions/{second.id}/debrief", headers=bearer(funded_account.user_id)
        )
    ).json()

    assert body["pressed"] == "harder"


async def test_a_first_room_has_nothing_to_compare_itself_to(
    client, db, engine, sessions, settlement, funded_account, bearer, weakness_reader
):
    """Null, and the client says nothing at all.

    "The room pressed as hard as last time" is a sentence about a session that
    does not exist, on the screen a first-time user reaches after the single
    most demanding thing this product does to them.
    """
    only = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    await _ran_at(db, only.id, GENTLE)

    body = (
        await client.get(
            f"/v1/sessions/{only.id}/debrief", headers=bearer(funded_account.user_id)
        )
    ).json()

    assert body["pressed"] is None


async def _ran_at(db, session_id, level: int) -> None:
    """The rung the room was assembled at, as `build_room` would have written it."""
    await db.execute(
        update(Session).where(Session.id == session_id).values(difficulty_level=level)
    )
    await db.commit()


async def test_a_room_at_the_same_rung_says_nothing(
    client, db, engine, sessions, settlement, funded_account, bearer, weakness_reader
):
    """Null rather than a third word, and the third word would be a lie.

    Without this the comparison falls through to its own else and reports
    "easier" for a room that pushed exactly as hard — a sentence contradicting
    what the person just sat through, on the screen where the product is asking
    them to trust its reading of the room.

    Nothing changed, so nothing is said. The debrief screen is already carrying
    weak answers and a coach; a line announcing that the difficulty held steady
    is noise at best.
    """
    first = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    await _ran_at(db, first.id, STANDARD)
    second = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    await _ran_at(db, second.id, STANDARD)

    body = (
        await client.get(
            f"/v1/sessions/{second.id}/debrief", headers=bearer(funded_account.user_id)
        )
    ).json()

    assert body["pressed"] is None
