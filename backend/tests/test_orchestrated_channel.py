"""The room, run by us rather than by a vendor.

ElevenLabs Agents hands a whole conversation to one remote agent. That cannot
be a Flintroom panel: the turn-taking, the grounded challenge, the targeted
interruption and the archetype separation all live in `app/agents/`, and none of
them exist inside somebody else's conversational agent.

So this provider satisfies the same `VoiceChannel` contract while owning the loop
— transcribe, decide who speaks, write their line, speak it. The relay does not
know the difference, which is the whole point of the seam and the reason nothing
in `relay.py` changes.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

import pytest

from app.agents.archetypes import DEFAULT_PANEL, Archetype
from app.agents.context import Grounding
from app.agents.model import ModelReply
from app.modules.voice.events import AgentTranscript, Spent
from app.modules.voice.orchestrated import OrchestratedChannel
from app.modules.voice.transcribers.elevenlabs import SAMPLE_RATE
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


class FakeSpeaker:
    """Synthesis without a vendor. Two frames, so chunking is visible."""

    def __init__(self) -> None:
        self.spoke: list[tuple[str, str | None]] = []

    async def speak(self, *, text: str, voice: str | None) -> AsyncIterator[bytes]:
        self.spoke.append((text, voice))
        yield b"\x01\x02"
        yield b"\x03\x04"


class ScriptedPanelModel:
    """Answers with a fixed speaker and a fixed line, and records what it saw."""

    def __init__(self, *, speaker: str = "cfo", line: str = "Where is that from?") -> None:
        self._speaker = speaker
        self._line = line
        self.composed_for: list[str] = []
        self.said: list[str] = []

    async def select(self, *, candidates: Sequence[Archetype], context) -> ModelReply:
        return ModelReply(text=self._speaker)

    async def compose(self, *, archetype: Archetype, context, finding=None) -> ModelReply:
        self.composed_for.append(archetype.name)
        self.said.append(context.said)
        return ModelReply(text=self._line)


async def events_of(channel: OrchestratedChannel) -> list:
    return [event async for event in channel.events()]


async def test_the_room_reports_itself_open_before_anyone_speaks():
    """Without this the session never leaves `provisioning` and is reaped.

    `ChannelReady` is what the relay turns into `activate()`, and activation is
    what opens the billable interrogation span. A channel that never sends one
    would leave a room the user can hear and talk to, that the ledger believes
    never started, still holding their one-session lock until the sweep.

    First, and before any transcription. It reports that the channel exists, not
    that anybody has used it — a user who says nothing for the first thirty
    seconds is in a room that opened, and the idle timeout is what decides
    otherwise.
    """
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription([]),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
    )

    events = await events_of(channel)

    assert [type(event).__name__ for event in events] == ["ChannelReady"]


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
        "ChannelReady",
        "UserSpoke",
        "AgentTranscript",
        # No speaker on this channel, so `Spent` still reports the model's
        # tokens and zero characters — nothing was synthesised to charge for.
        "Spent",
    ]


async def two_turns(model, grounding: Grounding, said: Sequence[str]) -> None:
    """Run a room across two utterances, letting each turn finish first.

    Turn by turn rather than from a fixed script, because a script yields both
    finals in the same tick — and the channel is right to treat that as the user
    talking through the panel's answer and abandon the first turn. No transcriber
    behaves that way; the pacing has to be in the test, not designed around.
    """
    transcription = DrivenTranscription()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=transcription,
        model=model,
        grounding=grounding,
    )

    spoken = asyncio.Queue()

    async def collect():
        async for event in channel.events():
            if isinstance(event, AgentTranscript):
                spoken.put_nowait(event)

    reader = asyncio.create_task(collect())
    for utterance in said:
        transcription.feed(Transcription(text=utterance, final=True))
        await asyncio.wait_for(spoken.get(), timeout=1)
    transcription.hang_up()
    await asyncio.wait_for(reader, timeout=1)


async def test_the_second_turn_can_see_the_first():
    """A room, not a sequence of unrelated questions.

    Both sides accumulate, and both matter. Without the panel's own lines a
    composer repeats itself; without the user's answers a selector cannot tell
    whether anything was actually answered, and pressing an evaded question is
    the single most useful thing a panel does.
    """
    seen: list[tuple[str, ...]] = []

    class Watching(ScriptedPanelModel):
        async def compose(self, *, archetype, context, finding=None) -> ModelReply:
            seen.append(
                tuple(line.text for line in context.grounding.transcript)
            )
            return ModelReply(text="And the one before that?")

    await two_turns(
        Watching(),
        Grounding(),
        ["Margin is seventy percent.", "It improved last quarter."],
    )

    assert seen[0] == ("Margin is seventy percent.",)
    assert seen[1] == (
        "Margin is seventy percent.",
        "And the one before that?",
        "It improved last quarter.",
    )


async def test_a_user_who_talks_through_the_answer_is_still_on_record():
    """Choosing not to reply must not erase what they said.

    A second finished utterance while a turn is in flight abandons that turn —
    the room answers the latest thing said, rather than queueing a challenge to a
    sentence the user has already moved on from. But the abandoned turn is *our*
    decision, and their words are not ours to drop: the next selection would
    otherwise judge the conversation without an answer it was actually given.
    """
    seen: list[tuple[str, ...]] = []

    class Watching(ScriptedPanelModel):
        async def compose(self, *, archetype, context, finding=None) -> ModelReply:
            seen.append(tuple(line.text for line in context.grounding.transcript))
            return ModelReply(text="Against what basis?")

    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [
                Transcription(text="Margin is seventy percent.", final=True),
                Transcription(text="Well — closer to sixty.", final=True),
            ]
        ),
        model=Watching(),
        grounding=Grounding(),
    )

    await events_of(channel)

    # One turn ran, and it saw both sentences the user managed to get out.
    assert seen == [("Margin is seventy percent.", "Well — closer to sixty.")]


async def test_the_deck_stays_in_front_of_every_turn():
    """Claims do not decay as the transcript grows.

    The wedge, mechanically: `CLAUDE.md` refuses to ship interrogation logic that
    cannot cite its source, and a room that carried the deck on turn one and
    forgot it by turn four would degrade into exactly the generic hard questions
    Open Risk #2 names as the fastest way to lose a user.
    """
    seen: list[tuple[str, ...]] = []

    class Watching(ScriptedPanelModel):
        async def compose(self, *, archetype, context, finding=None) -> ModelReply:
            seen.append(context.grounding.claims)
            return ModelReply(text="Where is that from?")

    await two_turns(
        Watching(),
        Grounding(claims=("Gross margin of 61% in Q3 2026 (slide 4)",)),
        ["Margin is seventy percent.", "And growing."],
    )

    assert seen[0] == seen[1] == ("Gross margin of 61% in Q3 2026 (slide 4)",)


async def test_the_line_is_spoken_in_that_archetypes_own_voice():
    """Distinct voices are why this vendor was chosen at all (`CLAUDE.md`).

    A panel that sounds like one person reading four scripts is not a panel, and
    the user cannot tell who is challenging them without looking at a phone the
    product's whole premise says is face-down on the desk.

    The caption goes first. Audio arrives in chunks over the length of an
    utterance, so a client that had to wait for the last frame to display the
    line would caption the room several seconds late — and captions are a v1
    accessibility requirement, not a garnish.
    """
    speaker = FakeSpeaker()
    # Voices assigned here rather than read from the library, which still has
    # none: the behaviour under test is that the *speaking* archetype's voice is
    # the one used, and asserting that against a panel of `None`s would pass
    # whichever archetype was handed over.
    panel = tuple(
        archetype.model_copy(update={"voice": f"voice_{archetype.name}"})
        for archetype in DEFAULT_PANEL
    )
    channel = OrchestratedChannel(
        panel=panel,
        transcription=FakeTranscription(
            [Transcription(text="Margin is seventy percent.", final=True)]
        ),
        model=ScriptedPanelModel(speaker="cfo", line="Against what basis?"),
        speaker=speaker,
        grounding=Grounding(),
    )

    events = await events_of(channel)

    assert [type(event).__name__ for event in events] == [
        "ChannelReady",
        "UserSpoke",
        "AgentTranscript",
        # Before the audio, because both providers have already charged by the
        # time the first frame exists — see `_turn`.
        "Spent",
        "AgentAudio",
        "AgentAudio",
    ]
    assert speaker.spoke == [("Against what basis?", "voice_cfo")]


class DrivenTranscription:
    """A transcription stream the test feeds by hand, result by result.

    Barge-in is a race by definition — the user speaks *while* a panelist is
    speaking — and a fixed script cannot express one. This lets a test say
    "now, mid-utterance" and have it mean that.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Transcription | None] = asyncio.Queue()

    def feed(self, result: Transcription) -> None:
        self._queue.put_nowait(result)

    def hang_up(self) -> None:
        self._queue.put_nowait(None)

    async def send_audio(self, pcm: bytes) -> None:
        pass

    async def results(self) -> AsyncIterator[Transcription]:
        while (result := await self._queue.get()) is not None:
            yield result


class GatedSpeaker:
    """Speaks one frame, then blocks until the test lets it continue."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = False

    async def speak(self, *, text: str, voice: str | None) -> AsyncIterator[bytes]:
        yield b"\x01\x02"
        self.started.set()
        await self.release.wait()
        yield b"\x03\x04"
        self.finished = True


async def test_speaking_over_a_panelist_stops_them():
    """The feature the whole voice layer was chosen for (Product.md §5.1).

    Two obligations, and the second is the one that is easy to miss. Stopping
    synthesis is not enough on its own: audio runs ahead of playback, so frames
    the panelist will never finish are already buffered on the phone, and letting
    those play is the room failing to be interruptible. `Interrupted` is what
    tells the relay to drop them.

    A **partial** triggers this, not a final. Waiting for the user to finish
    their sentence before conceding the floor is not barge-in — it is a panelist
    talking over somebody for three seconds and then stopping politely.
    """
    speaker = GatedSpeaker()
    transcription = DrivenTranscription()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=transcription,
        model=ScriptedPanelModel(line="Against what basis?"),
        speaker=speaker,
        grounding=Grounding(),
    )

    collected = []

    async def collect():
        async for event in channel.events():
            collected.append(event)

    reader = asyncio.create_task(collect())
    transcription.feed(Transcription(text="Margin is seventy.", final=True))
    await asyncio.wait_for(speaker.started.wait(), timeout=1)

    # The user cuts in, mid-sentence, before the panelist has finished.
    transcription.feed(Transcription(text="No, wait —", final=False))
    await asyncio.sleep(0)
    transcription.hang_up()
    await asyncio.wait_for(reader, timeout=1)

    assert any(type(event).__name__ == "Interrupted" for event in collected)
    assert not speaker.finished, "the cut-off panelist kept synthesising"


async def test_a_turn_reports_what_it_spent():
    """Three vendors bill for one turn, and the room says so.

    Until the panel was ours, a room was one agent on one opaque per-minute
    rate and recording its duration was very nearly enough. A turn now spends
    money in three places — the transcriber by the second, the panel model by
    the token, synthesis by the character — and Open Risk #4 says every margin
    in §4.4 rests on an unverified $0.12/min that nothing could contradict.

    The character count is the one worth watching. It tracks how much the panel
    *talks*, not how long the room lasts, so two rooms of equal length can cost
    materially different amounts — which makes the 25-word limit a cost lever as
    well as a credibility one.
    """
    model = ScriptedPanelModel(line="Where is that from?")
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [Transcription(text="Our gross margin is seventy percent.", final=True)]
        ),
        model=model,
        speaker=FakeSpeaker(),
        grounding=Grounding(),
    )

    events = await events_of(channel)

    (spent,) = [event for event in events if isinstance(event, Spent)]
    assert spent.tts_characters == len("Where is that from?")


async def test_the_audio_a_room_listened_to_is_charged_for_once():
    """Scribe bills for every second it hears, not for the seconds we answer.

    Counted from the bytes actually forwarded rather than from the room's wall
    clock, because those differ in the direction that costs money: a phone that
    reconnects, or a user who pauses the stream, is wall-clock time nobody was
    transcribed for. Wall clock is what the *user* is charged; this is what the
    vendor charges us, and conflating them is how a margin looks fine and is not.

    Reported once. Two turns must not each claim the whole room's audio, which
    would inflate the recorded cost by the number of questions asked — worst on
    exactly the rooms that worked best.
    """
    speech = b"\x00" * (SAMPLE_RATE * 2)  # one second of PCM16 at 16 kHz
    transcription = DrivenTranscription()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=transcription,
        model=ScriptedPanelModel(),
        grounding=Grounding(),
    )

    async def feed():
        await channel.send_audio(speech * 3)
        transcription.feed(Transcription(text="Margin is seventy percent.", final=True))
        # A turn has to be allowed to run and report before the next audio
        # arrives, or both finals land in one tick and the test is measuring
        # scheduling rather than accounting.
        await asyncio.sleep(0.05)
        await channel.send_audio(speech * 2)
        transcription.feed(Transcription(text="And it holds at scale.", final=True))
        await asyncio.sleep(0.05)
        transcription.hang_up()

    events, _ = await asyncio.gather(events_of(channel), feed())

    spent = [event for event in events if isinstance(event, Spent)]
    assert [report.stt_seconds for report in spent] == [3, 2]
