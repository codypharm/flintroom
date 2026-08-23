"""The room a presenter walks back into — docs/reconnect.md decision 4.

Met with silence, a presenter back from a tunnel cannot tell whether the
reconnect worked, and the illusion of a live room dies in that uncertainty.
So the room speaks first — one hand-written line, no model call — and which
line depends on whose turn the transcript says it was when the line dropped.
The panel says exactly one thing about the disconnect and never scores it.
"""

from __future__ import annotations

import pytest

from app.agents.archetypes import DEFAULT_PANEL, by_name
from app.agents.context import USER, Grounding, Said
from app.agents.opening import reentry_from
from app.modules.sessions.models import TranscriptLine
from app.modules.sessions.service import SessionService
from app.modules.voice.events import AgentTranscript
from app.modules.voice.orchestrated import OrchestratedChannel
from app.modules.voice.room import build_room
from app.modules.voice.transcription import Transcription

from tests.test_orchestrated_channel import (
    FakeTranscription,
    ScriptedPanelModel,
    events_of,
)
from tests.test_room import FakePanelModel, FakeTranscriber

pytestmark = pytest.mark.asyncio


MID_ANSWER = (
    Said(speaker="cfo", text="Walk me through the acquisition cost."),
    Said(speaker=USER, text="It runs about twelve hundred dollars, and"),
)

MID_QUESTION = (
    Said(speaker=USER, text="Margins are seventy percent."),
    Said(speaker="cfo", text="Seventy on which line — gross or contribution?"),
)


def first_agent_line(events) -> AgentTranscript | None:
    return next(
        (event for event in events if isinstance(event, AgentTranscript)), None
    )


async def test_a_resumed_room_speaks_first_and_it_is_not_the_opener():
    """The opener belongs to a room that holds nothing; this room holds a
    conversation. What the presenter hears on walking back in is the panelist
    who had the floor taking it back, in their own hand-written words."""
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription([]),
        model=ScriptedPanelModel(),
        grounding=Grounding(transcript=MID_ANSWER),
        resuming=True,
    )

    events = await events_of(channel)

    spoken = first_agent_line(events)
    assert spoken is not None
    assert spoken.speaker == "cfo"
    assert spoken.text in by_name("cfo").reentries
    openers = {line for one in DEFAULT_PANEL for line in one.openers}
    assert spoken.text not in openers


async def test_a_question_the_tunnel_may_have_eaten_is_asked_again():
    """A panel line is recorded before it is spoken, so a drop mid-question
    means the transcript holds words the presenter may never have heard. The
    same panelist says them again, verbatim — re-synthesis, not a model call."""
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription([]),
        model=ScriptedPanelModel(),
        grounding=Grounding(transcript=MID_QUESTION),
        resuming=True,
    )

    events = await events_of(channel)

    spoken = first_agent_line(events)
    assert spoken is not None
    assert spoken.speaker == "cfo"
    assert spoken.text == "Seventy on which line — gross or contribution?"


async def test_a_resumed_room_answers_the_next_final_as_an_ordinary_turn():
    """No second opening statement. The floor closed minutes ago, so the
    first thing said after the reconnect is an answer to be judged, not an
    opening to be waited out."""
    model = ScriptedPanelModel()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [Transcription(text="As I was saying, payback lands in month seven.", final=True)]
        ),
        model=model,
        grounding=Grounding(transcript=MID_ANSWER),
        resuming=True,
    )

    await events_of(channel)

    assert model.said == ["As I was saying, payback lands in month seven."]


def test_the_go_on_falls_to_whoever_last_held_the_floor():
    transcript = (
        Said(speaker="champion", text="What would you build with twice the budget?"),
        Said(speaker=USER, text="Honestly, the same thing, faster."),
        Said(speaker="cfo", text="Faster at what burn?"),
        Said(speaker=USER, text="About forty thousand a month, and"),
    )

    who, line = reentry_from(DEFAULT_PANEL, transcript)

    assert who.name == "cfo"
    assert line in who.reentries


def test_a_room_that_dropped_before_anyone_spoke_still_reenters():
    """The presenter heard the opener (it is spoken, never persisted) and
    then the line died. Somebody at the table hands them the floor back."""
    who, line = reentry_from(DEFAULT_PANEL, ())

    assert line in who.reentries


def test_every_shipped_archetype_can_take_the_floor_back():
    """Hand-written like `openers` and `nudges`, and complete for the same
    reason: a room is seated from this library, and a seat with no line is a
    resume met with silence."""
    for one in DEFAULT_PANEL:
        assert one.reentries, f"{one.name} has no re-entry lines"
        for line in one.reentries:
            assert line.strip()


async def test_a_room_built_over_a_transcript_knows_it_is_resuming(db, funded_account):
    """`build_room` is the seam: the persisted lines come back as the room's
    memory, and their existence is what marks the room a resume — covering
    the supersede case, where the reconnect lands before the stamp does."""
    sessions = SessionService(db)
    session = await sessions.start(
        user_id=funded_account.user_id, archetypes=["cfo"]
    )
    db.add(
        TranscriptLine(
            session_id=session.id,
            ordinal=0,
            speaker="cfo",
            text="What does a seat cost you?",
        )
    )
    await db.commit()

    room = await build_room(
        db,
        session_id=session.id,
        user_id=funded_account.user_id,
        transcriber=FakeTranscriber(),
        model=FakePanelModel(),
    )

    assert room.resuming
    assert [one.text for one in room.memory] == ["What does a seat cost you?"]


async def test_a_fresh_room_is_not_resuming(db, funded_account):
    session = await SessionService(db).start(
        user_id=funded_account.user_id, archetypes=["cfo"]
    )

    room = await build_room(
        db,
        session_id=session.id,
        user_id=funded_account.user_id,
        transcriber=FakeTranscriber(),
        model=FakePanelModel(),
    )

    assert not room.resuming
    assert room.memory == ()
