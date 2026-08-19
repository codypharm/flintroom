"""The opening floor, inside a live room.

#79. `test_opening_floor.py` proves the arithmetic; this proves the room obeys
it — that nobody composes a challenge while the presenter is still making their
case, and that everything else keeps running while they do.

That second half is the part worth guarding. It would be easy to "pause the
room" during the opening and quietly stop filing the transcript or feeding the
Auditor, which would cost the debrief its grounding and the panel its best
catch — the two things the floor exists to create.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.archetypes import DEFAULT_PANEL
from app.agents.context import USER, Grounding
from app.agents.opening import OpeningFloor
from app.modules.voice.events import (
    AgentAudio,
    AgentFinished,
    AgentTranscript,
    Attending,
    Attention,
    Heartbeat,
)
from app.modules.voice.orchestrated import OrchestratedChannel
from app.modules.voice.transcription import Transcription

from tests.test_orchestrated_channel import (
    FakeSpeaker,
    FakeTranscript,
    FakeTranscription,
    ScriptedPanelModel,
    events_of,
)

pytestmark = pytest.mark.asyncio


class HeldOpenTranscription(FakeTranscription):
    """A transcriber that outlives the utterance, as a real one does.

    `TranscriptionStream.results` is explicit that it "ends when the connection
    does, not when the user goes quiet" — silence is an ordinary part of a
    hostile Q&A. `FakeTranscription` ends the moment its script runs out, which
    is fine for a room that answers every final immediately and useless for one
    that deliberately waits: the stream would close, `_listen` would put `None`,
    and the room would be torn down before the floor ever settled.

    So this holds the socket open until the test lets it go, which is what makes
    "the panel spoke *after* the presenter finished" observable at all.
    """

    def __init__(self, results, *, release: asyncio.Event, gap: float = 0.0) -> None:
        super().__init__(results)
        self.release = release
        self._gap = gap

    async def results(self):
        for result in self._results:
            yield result
            # Real speech arrives seconds apart. A fake that emits a whole
            # conversation without yielding control hands the room every
            # utterance before the floor has had a chance to close, which is a
            # timing no presenter can produce.
            if self._gap:
                await asyncio.sleep(self._gap)
        await self.release.wait()


def held_open(results, *, gap: float = 0.0) -> HeldOpenTranscription:
    return HeldOpenTranscription(results, release=asyncio.Event(), gap=gap)


async def room_until_composed(channel, model, *, turns: int = 1) -> list:
    """Run the room until the panel has spoken, then hang up.

    Polling rather than sleeping: what these tests care about is the *order* of
    events, and a fixed sleep would either be slower than it needs to be or
    flaky on a loaded machine.
    """
    collecting = asyncio.create_task(events_of(channel))

    async def composed() -> None:
        while len(model.composed_for) < turns:
            await asyncio.sleep(0)

    try:
        await asyncio.wait_for(composed(), timeout=5)
    finally:
        channel._transcription.release.set()  # noqa: SLF001

    return await collecting


def opening(words: int) -> str:
    return " ".join(["margin"] * words)


def held(**kwargs) -> OpeningFloor:
    """A floor that settles instantly unless a test says otherwise.

    Real time in a test is a flake waiting to happen; what is under test here is
    the *ordering*, not the clock, and `test_opening_floor.py` already owns the
    clock.
    """
    return OpeningFloor(**{"substance": 10, "settle": 0.0, **kwargs})


async def test_the_room_opens_out_loud():
    """Screen-only is not hands-free — the phone is face-up on a desk.

    The presenter is told the floor is theirs by a voice, because nobody is
    looking at the screen. Without this the room's first act is silence, which
    is indistinguishable from a product that has crashed.
    """
    speaker = FakeSpeaker()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription([]),
        model=ScriptedPanelModel(),
        speaker=speaker,
        grounding=Grounding(),
        floor=held(),
    )

    events = await events_of(channel)
    captions = [event for event in events if isinstance(event, AgentTranscript)]

    assert len(captions) == 1
    who = next(one for one in DEFAULT_PANEL if one.name == captions[0].speaker)
    assert captions[0].text in who.openers


async def test_no_model_writes_the_opener():
    """The line is spoken when the room holds nothing at all.

    Asking a model to compose there is asking it to invent, which is the entire
    bug. A constant cannot hallucinate — and this is what stops somebody
    "improving" the opener into a generated one later.
    """
    model = ScriptedPanelModel()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription([]),
        model=model,
        grounding=Grounding(),
        floor=held(),
    )

    await events_of(channel)

    assert model.composed_for == []
    assert model.routed_on == []


async def test_the_opener_is_spoken_in_that_archetypes_voice():
    """A voice belonging to nobody at the table would be a narrator."""
    speaker = FakeSpeaker()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription([]),
        model=ScriptedPanelModel(),
        speaker=speaker,
        grounding=Grounding(),
        floor=held(),
    )

    events = await events_of(channel)
    captions = [event for event in events if isinstance(event, AgentTranscript)]
    who = next(one for one in DEFAULT_PANEL if one.name == captions[0].speaker)

    assert speaker.spoke == [(captions[0].text, who.voice)]
    assert any(isinstance(event, AgentAudio) for event in events)
    assert any(isinstance(event, AgentFinished) for event in events)


async def test_nobody_challenges_the_first_breath():
    """THE BUG. Finals commit after 0.7s of silence; openings pause longer.

    Two finals that are one thought. Before the floor existed, the first of them
    started a turn — so the panel answered half a sentence, and on a live device
    invented the subject of the other half.
    """
    model = ScriptedPanelModel()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=held_open(
            [
                Transcription(text=opening(6), final=True),
                Transcription(text=opening(6), final=True),
            ]
        ),
        model=model,
        grounding=Grounding(),
        # Settles only when nothing more arrives, which the scripted
        # transcription only reaches at the end.
        floor=held(substance=10, settle=0.05),
    )

    await room_until_composed(channel, model)

    assert len(model.composed_for) == 1, "the panel spoke before they had finished"
    assert model.said == [f"{opening(6)} {opening(6)}"]


async def test_the_first_challenge_sees_the_whole_opening():
    """Composed against the statement, not the fragment that happened to be last.

    `_answer` takes one `said`, and grounding the room's first challenge in the
    tail of a sentence is how you get a question about the wrong thing.
    """
    model = ScriptedPanelModel()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=held_open(
            [
                Transcription(text="We move freight.", final=True),
                Transcription(text="Margin is thirty per cent.", final=True),
            ]
        ),
        model=model,
        grounding=Grounding(),
        floor=held(substance=1, settle=0.05),
    )

    await room_until_composed(channel, model)

    assert model.said == ["We move freight. Margin is thirty per cent."]


async def test_the_transcript_still_fills_while_the_room_is_listening():
    """The floor stops the panel interrupting. It stops nothing else.

    A version that "paused the room" would cost the debrief its grounding —
    `session_transcript_lines` is exactly what §3.5 ranks weak answers against,
    and the opening statement is the densest thing in it.
    """
    store = FakeTranscript()
    model = ScriptedPanelModel()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=held_open(
            [
                Transcription(text="We move freight.", final=True),
                Transcription(text="Margin is thirty per cent.", final=True),
            ]
        ),
        model=model,
        grounding=Grounding(),
        transcript=store,
        floor=held(substance=1, settle=0.05),
    )

    await room_until_composed(channel, model)
    spoken = [line.text for line in store.lines if line.speaker == USER]

    assert spoken == ["We move freight.", "Margin is thirty per cent."]


async def test_a_thin_opening_earns_a_question_rather_than_a_challenge():
    """Your idea, with a code-checkable trigger.

    Not "the grounding feels thin" — a model judgement, and #43 measured what
    those are worth — but *they stopped, and said less than the substance
    floor*. The composer is told; what it asks is still its own.
    """
    model = ScriptedPanelModel()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=held_open(
            [Transcription(text="Hi. So, yeah.", final=True)]
        ),
        model=model,
        grounding=Grounding(),
        floor=held(substance=60),
    )

    await room_until_composed(channel, model)

    assert model.contexts[0].thin_opening


async def test_a_full_opening_is_challenged_not_interviewed():
    """The orienting turn is the exception, and must stay one.

    A room that asks what you do after you have just told it is a room that was
    not listening.
    """
    model = ScriptedPanelModel()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=held_open(
            [Transcription(text=opening(70), final=True)]
        ),
        model=model,
        grounding=Grounding(),
        floor=held(substance=60),
    )

    await room_until_composed(channel, model)

    assert not model.contexts[0].thin_opening


async def test_the_floor_is_only_ever_the_first_stretch():
    """Once it closes, the room is the room it always was.

    Every later utterance is answered immediately — the settle pause is an
    opening-statement affordance, not a new rhythm for the whole session.
    """
    model = ScriptedPanelModel()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=held_open(
            [
                Transcription(text=opening(12), final=True),
                Transcription(text="Twenty.", final=True),
                Transcription(text="Thirty.", final=True),
            ],
            # Wider than the settle, so the opening closes before the answers
            # arrive — which is what makes this a test of the room after the
            # floor rather than of three utterances racing it.
            gap=0.05,
        ),
        model=model,
        grounding=Grounding(),
        floor=held(substance=10),
    )

    await room_until_composed(channel, model, turns=3)

    assert model.said == [opening(12), "Twenty.", "Thirty."]


async def test_a_presenter_who_never_stops_is_eventually_interrogated():
    """Without the cap, a twelve-minute monologue is a room nobody attended."""
    model = ScriptedPanelModel()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=held_open(
            [Transcription(text=opening(12), final=True)]
        ),
        model=model,
        grounding=Grounding(),
        # Never settles; only the cap can close this floor.
        floor=OpeningFloor(substance=10, settle=30.0, cap=0.05),
    )

    await room_until_composed(channel, model)

    assert model.composed_for, "the cap never fired"


async def test_the_opener_is_spoken_by_the_unhurried_voice():
    """#34. The room's two voices, and which line gets which.

    Eleven v3 performs audio tags and is 0.39s slower to its first byte
    (docs/voice-cost.md). An interrogation turn cannot afford that — the
    listener is already waiting ~2.1s against a ~1.5s threshold — but the
    opener is spoken into silence, before anybody has said a word, so there is
    nobody to keep waiting. It is the one line in the room where expressiveness
    is free in the currency that matters.
    """
    quick = FakeSpeaker()
    unhurried = FakeSpeaker()
    model = ScriptedPanelModel(line="And against what revenue?")
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=held_open([Transcription(text=opening(12), final=True)]),
        model=model,
        speaker=quick,
        opener_speaker=unhurried,
        grounding=Grounding(),
        floor=held(substance=10),
    )

    await room_until_composed(channel, model)

    spoken_openers = [line for line, _ in unhurried.spoke]
    assert len(spoken_openers) == 1
    assert any(spoken_openers[0] in one.openers for one in DEFAULT_PANEL)

    # And the challenge went the fast way, which is the half that protects the
    # room. A regression that sent turns to the expressive voice would sound
    # better and fail the thing the product is.
    assert [line for line, _ in quick.spoke] == ["And against what revenue?"]


async def test_the_room_still_opens_when_there_is_only_one_voice():
    """A deployment configured with a single synthesiser still opens out loud.

    The expressive speaker is optional in the way every other provider here is:
    losing it should cost the opener its texture, never its existence.
    """
    only = FakeSpeaker()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription([]),
        model=ScriptedPanelModel(),
        speaker=only,
        grounding=Grounding(),
        floor=held(),
    )

    events = await events_of(channel)
    captions = [event for event in events if isinstance(event, AgentTranscript)]

    assert only.spoke and only.spoke[0][0] == captions[0].text


async def test_the_room_says_it_is_still_listening_when_nobody_has_spoken():
    """#24, first half. Five things look like silence and this tells three apart.

    Reported after a day of testing: a room that heard nothing and a room that
    is thinking are the same screen, so the presenter waits, doubts, and ends
    the session. Only the server knows whether a final arrived, so no amount of
    cleverness on the phone can separate them — it has to be told.
    """
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription([]),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        floor=held(),
    )

    events = await events_of(channel)
    said = [event.state for event in events if isinstance(event, Attending)]

    assert said and said[0] is Attention.LISTENING


async def test_the_room_says_it_has_you_while_the_floor_is_still_yours():
    """The value that earns its place.

    During the opening floor a presenter may talk for ninety seconds across
    several finals with nobody replying. Without this, the floor built in #79
    is indistinguishable from the failure reported in #77 — and the fix for one
    reads as the other.
    """
    model = ScriptedPanelModel()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=held_open(
            [Transcription(text=opening(6), final=True)], gap=0.05
        ),
        model=model,
        grounding=Grounding(),
        # Never settles on its own, so the floor stays open and holding.
        floor=OpeningFloor(substance=60, settle=30.0, cap=30.0),
    )

    collecting = asyncio.create_task(events_of(channel))
    try:
        async def holding() -> None:
            while True:
                await asyncio.sleep(0)
                if channel._attention() is Attention.HEARD:  # noqa: SLF001
                    return
        await asyncio.wait_for(holding(), timeout=5)
    finally:
        channel._transcription.release.set()  # noqa: SLF001
        await collecting


async def test_the_room_says_it_is_working_once_it_owes_an_answer():
    """The other half of the pair. A turn in flight is not a room gone quiet."""
    model = ScriptedPanelModel()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=held_open([Transcription(text=opening(12), final=True)]),
        model=model,
        grounding=Grounding(),
        floor=held(substance=10),
    )

    events = await room_until_composed(channel, model)
    said = [event.state for event in events if isinstance(event, Attending)]

    assert Attention.WORKING in said


async def test_the_state_is_derived_rather_than_remembered():
    """Nothing has to remember to clear it, so nothing can leave it stuck.

    A reported state that is stored gets stranded by the paths that fail — a
    turn that dies leaves the room claiming to be working forever, which is
    worse than the silence it replaced because it is confidently wrong. That is
    this morning's `turn_finished` bug in a new place.

    Computed at the moment of sending, there is no transition to miss.
    """
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription([]),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        floor=held(),
    )

    assert channel._attention() is Attention.LISTENING  # noqa: SLF001


async def test_the_heartbeat_carries_the_state_even_when_it_has_not_changed():
    """The safety net, and it is why a missed message cannot be permanent.

    Transitions are sent for speed; this is sent for correctness. Suppressing a
    repeat here would mean a phone that dropped one message stayed wrong for
    the rest of the room.
    """
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=held_open([]),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        floor=held(),
        heartbeat_seconds=0.02,
    )

    collecting = asyncio.create_task(events_of(channel))
    await asyncio.sleep(0.12)
    channel._transcription.release.set()  # noqa: SLF001
    events = await collecting

    beats = [e for e in events if isinstance(e, Heartbeat)]
    states = [e for e in events if isinstance(e, Attending)]

    assert len(beats) >= 2
    assert len(states) >= len(beats), "the heartbeat stopped carrying the state"
