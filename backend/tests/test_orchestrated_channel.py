"""The room, run by us rather than by a vendor.

`ElevenLabsProvider` hands a whole conversation to one remote agent. That cannot
be a Flintroom panel: the turn-taking, the grounded challenge, the targeted
interruption and the archetype separation all live in `app/agents/`, and none of
them exist inside somebody else's conversational agent.

So this provider satisfies the same `VoiceChannel` contract while owning the loop
— transcribe, decide who speaks, write their line, speak it. The relay does not
know the difference, which is the whole point of the seam and the reason nothing
in `relay.py` changes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import pytest

from app.agents.archetypes import DEFAULT_PANEL, Archetype
from app.agents.context import Grounding
from app.modules.voice.events import AgentTranscript
from app.modules.voice.orchestrated import OrchestratedChannel
from app.modules.voice.transcription import Transcription

pytestmark = pytest.mark.asyncio


class FakeTranscription:
    """A transcriber that replays a fixed script of results.

    Ends its iterator, which is what a real one does when the socket closes —
    and what lets a test collect a channel's events without a timeout.
    """

    def __init__(self, results: Sequence[Transcription]) -> None:
        self._results = results
        self.heard: list[bytes] = []

    async def send_audio(self, pcm: bytes) -> None:
        self.heard.append(pcm)

    async def results(self) -> AsyncIterator[Transcription]:
        for result in self._results:
            yield result


class ScriptedPanelModel:
    """Answers with a fixed speaker and a fixed line, and records what it saw."""

    def __init__(self, *, speaker: str = "cfo", line: str = "Where is that from?") -> None:
        self._speaker = speaker
        self._line = line
        self.composed_for: list[str] = []
        self.said: list[str] = []

    async def select(self, *, candidates: Sequence[Archetype], context) -> str:
        return self._speaker

    async def compose(self, *, archetype: Archetype, context, finding=None) -> str:
        self.composed_for.append(archetype.name)
        self.said.append(context.said)
        return self._line


async def events_of(channel: OrchestratedChannel) -> list:
    return [event async for event in channel.events()]


async def test_a_finished_utterance_becomes_a_panel_line():
    """The tracer bullet: audio in, a grounded challenge out.

    One archetype speaks, in their own voice, about the thing the user just
    said — the whole of Phase 3 reduced to the smallest claim that can fail.
    """
    model = ScriptedPanelModel(line="Seventy percent against a deck that says 61.")
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [Transcription(text="Our gross margin is seventy percent.", final=True)]
        ),
        model=model,
        grounding=Grounding(),
    )

    events = await events_of(channel)

    assert AgentTranscript("Seventy percent against a deck that says 61.") in events
    assert model.said == ["Our gross margin is seventy percent."]


async def test_a_partial_result_does_not_put_words_in_the_room():
    """Only a finished utterance is answered.

    Partials exist so selection can run while the user is still speaking — that
    overlap is the entire plan for getting under the 1.5s threshold, since the
    selection hop costs ~0.8s of it. But composing on one would have a panelist
    interrupt a sentence in progress with a challenge to its first four words,
    which is not barge-in, it is not listening.
    """
    model = ScriptedPanelModel()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [
                Transcription(text="Our gross margin", final=False),
                Transcription(text="Our gross margin is seventy", final=False),
            ]
        ),
        model=model,
        grounding=Grounding(),
    )

    events = await events_of(channel)

    assert model.composed_for == []
    assert not [event for event in events if isinstance(event, AgentTranscript)]


async def test_the_user_speaking_is_reported_before_the_panel_answers():
    """Without this the idle timeout reaps every room at ninety seconds.

    `UserSpoke` is what the relay turns into `record_speech`, and only user
    speech resets the idle clock — panel speech deliberately does not, because a
    room monologuing at nobody is the expensive failure that check exists to
    catch. An orchestrated channel that never emitted it would look, to the
    reaper, exactly like an abandoned phone.

    Before the answer, not after. Composition is a model round trip; ordering it
    second would leave the clock running across the slowest part of the turn, so
    a user who thinks for eighty seconds and then speaks is thrown out *while the
    panel is answering them*.
    """
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [Transcription(text="We built it ourselves.", final=True)]
        ),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
    )

    events = await events_of(channel)

    assert [type(event).__name__ for event in events] == [
        "UserSpoke",
        "AgentTranscript",
    ]


async def test_the_second_turn_can_see_the_first():
    """A room, not a sequence of unrelated questions.

    Both sides accumulate, and both matter. Without the panel's own lines a
    composer repeats itself; without the user's answers a selector cannot tell
    whether anything was actually answered, and pressing an evaded question is
    the single most useful thing a panel does.
    """
    seen: list[tuple[str, ...]] = []

    class Watching(ScriptedPanelModel):
        async def compose(self, *, archetype, context, finding=None) -> str:
            seen.append(
                tuple(line.text for line in context.grounding.transcript)
            )
            return "And the one before that?"

    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [
                Transcription(text="Margin is seventy percent.", final=True),
                Transcription(text="It improved last quarter.", final=True),
            ]
        ),
        model=Watching(),
        grounding=Grounding(),
    )

    await events_of(channel)

    assert seen[0] == ()
    assert seen[1] == ("Margin is seventy percent.", "And the one before that?")


async def test_the_deck_stays_in_front_of_every_turn():
    """Claims do not decay as the transcript grows.

    The wedge, mechanically: `CLAUDE.md` refuses to ship interrogation logic that
    cannot cite its source, and a room that carried the deck on turn one and
    forgot it by turn four would degrade into exactly the generic hard questions
    Open Risk #2 names as the fastest way to lose a user.
    """
    seen: list[tuple[str, ...]] = []

    class Watching(ScriptedPanelModel):
        async def compose(self, *, archetype, context, finding=None) -> str:
            seen.append(context.grounding.claims)
            return "Where is that from?"

    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [
                Transcription(text="Margin is seventy percent.", final=True),
                Transcription(text="And growing.", final=True),
            ]
        ),
        model=Watching(),
        grounding=Grounding(claims=("Gross margin of 61% in Q3 2026 (slide 4)",)),
    )

    await events_of(channel)

    assert seen[0] == seen[1] == ("Gross margin of 61% in Q3 2026 (slide 4)",)
