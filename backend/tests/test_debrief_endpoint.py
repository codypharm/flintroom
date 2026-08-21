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
    # Asks for the missing figure rather than supplying one, which is what makes
    # a suggestion safe to print at all — see `weakness._invents_a_figure`.
    next_time="Have the base and the cost ready before he asks a second time.",
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
            "next_time": (
                "Have the base and the cost ready before he asks a second time."
            ),
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
    # Everything readable is identical. The screen must not reshuffle under
    # somebody working through it, and the greeting must not be reworded either.
    assert first.json()["weak_answers"] == second.json()["weak_answers"]
    assert first.json()["pressed"] == second.json()["pressed"]
    assert first.json()["opening"]["text"] == second.json()["opening"]["text"]

    # The one thing that is deliberately NOT identical, and the reason is money.
    # `docs/voice-cost.md` puts the expressive speaker at roughly $0.0002 a
    # character, so a spoken opening costs about what a minute of live
    # interrogation does — and this is the request a backgrounded phone repeats.
    # Synthesised for the arrival it belongs to and not again; hearing it a
    # second time is a deliberate request with its own endpoint.
    assert first.json()["opening"]["speech"]
    assert second.json()["opening"]["speech"] == ""


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


async def test_the_opening_can_be_heard_again_when_it_is_asked_for(
    client, db, engine, sessions, settlement, funded_account, bearer, weakness_reader
):
    """The other half of speaking once.

    The greeting autoplays on arrival and is silent on every read after, which
    is right for a backgrounded phone and wrong for somebody who was on a train
    with the volume down. This is the way back, and it costs a synthesis at
    exactly the moment somebody asked for one.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    weakness_reader.judged = (FOUND,)
    headers = bearer(funded_account.user_id)
    opened = (
        await client.get(f"/v1/sessions/{session.id}/debrief", headers=headers)
    ).json()

    again = await client.post(
        f"/v1/sessions/{session.id}/debrief/opening/speech", headers=headers
    )

    assert again.status_code == 201
    assert again.json()["text"] == opened["opening"]["text"]
    assert again.json()["speech"]


async def test_hearing_an_opening_that_was_never_said_is_a_404(
    client, db, engine, sessions, settlement, funded_account, bearer, weakness_reader
):
    """A room whose coaching started at the microphone has no greeting to replay.

    404 rather than synthesising one on the spot: an opening minted here would
    be a greeting arriving in the middle of a conversation, and it would arrive
    because somebody pressed replay.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    weakness_reader.judged = (FOUND,)

    response = await client.post(
        f"/v1/sessions/{session.id}/debrief/opening/speech",
        headers=bearer(funded_account.user_id),
    )

    assert response.status_code == 404


async def test_one_user_cannot_replay_another_users_opening(
    client, db, engine, sessions, settlement, funded_account, bearer, ledger, weakness_reader
):
    """It costs a vendor call, so it is worth being explicit that it is owned."""
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    weakness_reader.judged = (FOUND,)
    await client.get(
        f"/v1/sessions/{session.id}/debrief", headers=bearer(funded_account.user_id)
    )
    stranger = await create_funded_account(db, ledger)

    response = await client.post(
        f"/v1/sessions/{session.id}/debrief/opening/speech",
        headers=bearer(stranger.user_id),
    )

    assert response.status_code == 404


async def test_two_attempts_at_one_rehearsal_are_compared_to_each_other(
    client, db, engine, sessions, settlement, funded_account, bearer, weakness_reader
):
    """The comparison a rehearsal actually wants: this attempt against the last.

    "They pressed harder *this time* than last" reads as a statement about the
    same thing tried twice, and since a re-run inherits the rung its rehearsal
    last ran at, that is the only pair whose difference means anything.
    """
    first = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    await _ran_at(db, first.id, GENTLE)
    again = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM, repeats=first.id
    )
    await _ran_at(db, again.id, RELENTLESS)

    body = (
        await client.get(
            f"/v1/sessions/{again.id}/debrief", headers=bearer(funded_account.user_id)
        )
    ).json()

    assert body["pressed"] == "harder"


async def test_a_rehearsal_is_never_compared_against_a_different_one(
    client, db, engine, sessions, settlement, funded_account, bearer, weakness_reader
):
    """The noise this exists to stop.

    A re-run opens at the rung its own rehearsal last ran at, so two rehearsals
    sitting at different rungs make every debrief say "harder", then "easier",
    then "harder" — while nothing about the presenter changed. Decision 5 built
    this sentence to give credit; one that oscillates on bookkeeping spends the
    credit it was for.
    """
    board = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    await _ran_at(db, board.id, RELENTLESS)
    demo = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    await _ran_at(db, demo.id, GENTLE)
    # Back to the board readout, which still sits where it sat.
    again = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM, repeats=board.id
    )
    await _ran_at(db, again.id, RELENTLESS)

    body = (
        await client.get(
            f"/v1/sessions/{again.id}/debrief", headers=bearer(funded_account.user_id)
        )
    ).json()

    # Against the board readout's own last attempt, which pressed exactly as
    # hard — not against the gentle demo-day room that happened in between.
    assert body["pressed"] is None
