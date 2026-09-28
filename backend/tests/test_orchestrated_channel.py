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
import logging
from collections.abc import AsyncIterator, Sequence

import pytest

from app.agents.archetypes import DEFAULT_PANEL, LIBRARY, Archetype
from app.agents.auditor import Auditor, ClaimReading
from app.agents.context import USER, Grounding, Said
from app.agents.model import ModelReply, TurnUsage
from app.core.errors import ProviderUnavailable
from app.modules.voice.events import (
    AgentAudio,
    AgentFinished,
    AgentTranscript,
    Heartbeat,
    Spent,
)
from app.agents.opening import OpeningFloor
from app.modules.voice.orchestrated import HEARTBEAT_SECONDS, OrchestratedChannel
from app.modules.voice.transcribers.elevenlabs import SAMPLE_RATE
from app.modules.ingestion.schemas import QuantitativeClaim, Unit
from app.modules.voice.mixing import RoomMixer
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

    def __init__(
        self,
        *,
        speaker: str = "cfo",
        line: str = "Where is that from?",
        rephrased: str | None = None,
    ) -> None:
        self._speaker = speaker
        self._line = line
        self._rephrased = rephrased
        self.rephrasings: list[str] = []
        self.composed_for: list[str] = []
        self.said: list[str] = []
        #: Every `TurnContext` the composer was handed, kept whole. Individual
        #: fields were being copied out one at a time as the context grew; the
        #: object is what the model actually sees, so a test asserting on a
        #: field nobody copied is the failure this avoids.
        self.contexts: list = []
        #: What each selection call was shown. The text matters as much as the
        #: count: routing off a partial is the entire latency plan, and a
        #: selection that saw the finished sentence is one that ran too late.
        self.routed_on: list[str] = []
        #: Set the moment a selection is entered, so a test can wait for routing
        #: to have *started* rather than sleep and hope.
        self.selecting = asyncio.Event()

    async def select(self, *, candidates: Sequence[Archetype], context) -> ModelReply:
        self.routed_on.append(context.said)
        self.selecting.set()
        return ModelReply(text=self._speaker)

    async def compose(
        self, *, archetype: Archetype, context, finding=None, dispute=None, rephrasing=None
    ) -> ModelReply:
        self.composed_for.append(archetype.name)
        #: Every question this fake was asked to put another way (#117). The
        #: text matters: a rephrase composed against anything other than the
        #: question already asked is one that can change what is being asked.
        if rephrasing is not None:
            self.rephrasings.append(rephrasing)
            return ModelReply(text=self._rephrased or self._line)
        self.said.append(context.said)
        self.contexts.append(context)
        return ModelReply(text=self._line)


class FakeTranscript:
    """A store that keeps the room in a list instead of a database.

    Asserted against directly, because the point of the seam is that the channel
    hands over whole lines and does not know where they land.
    """

    def __init__(self) -> None:
        self.lines: list[Said] = []
        #: Every line with the offset it was filed at — #69. Kept beside
        #: `lines` rather than folded into it so the tests that predate the
        #: clock keep reading what they always read.
        self.stamped: list[tuple[Said, float | None]] = []

    async def record(self, line: Said, *, at: float | None = None) -> None:
        self.lines.append(line)
        self.stamped.append((line, at))


class ScriptedClock:
    """The room's clock, moved by hand — #69.

    Stands in for `RoomMixer`, which is the real one. What it stands in for is a
    sample count, so a test can put the room at any second it likes without
    feeding it a second's worth of audio.
    """

    def __init__(self) -> None:
        self.at = 0.0

    def elapsed(self) -> float:
        return self.at


class TimedTranscription:
    """A transcriber that moves the room's clock as its results arrive.

    Real time passes between a partial and the final that closes it, and that
    gap is the entire thing under test: against a still clock, "stamped where
    they started" and "stamped where they stopped" are the same number.
    """

    def __init__(
        self, clock: ScriptedClock, script: Sequence[tuple[float, Transcription]]
    ) -> None:
        self._clock = clock
        self._script = script
        self.heard: list[bytes] = []

    async def send_audio(self, pcm: bytes) -> None:
        self.heard.append(pcm)

    async def results(self) -> AsyncIterator[Transcription]:
        for at, result in self._script:
            self._clock.at = at
            yield result


def mid_room() -> OpeningFloor:
    """A room already past its opening statement.

    #79 gave every room an opening floor: it speaks first, then listens without
    interrupting until the presenter settles. Almost every test in this file
    describes what happens *after* that — one utterance, one answer — and would
    otherwise have to re-describe the opening to get there.

    Handing over a floor that is already closed says exactly that, and says it
    in the domain's own terms. It is not a production configuration:
    `OrchestratedProvider.open` builds a fresh `OpeningFloor` per room, which
    `test_opening_in_the_room.py` is what covers.
    """
    return OpeningFloor(open=False)


def sequence(events) -> list[str]:
    """The events in order, without the room narrating about itself.

    #24 added `Attending` and #74 added `RoomTemperature`. Both are emitted on
    transitions and on every heartbeat, both are orthogonal to the orderings
    these tests are about, and together they are noisy enough to bury them.
    Each has its own coverage — `test_opening_in_the_room.py` and
    `test_room_temperature.py` — where the ordering that matters is its own.
    """
    narration = {"Attending", "RoomTemperature"}
    return [
        type(event).__name__
        for event in events
        if type(event).__name__ not in narration
    ]


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

    # First, and before the opener. #79 gave the room a spoken opening — the
    # property under test is the *ordering*, because `ChannelReady` is what
    # opens the billable span and everything audible has to come after it.
    assert [type(event).__name__ for event in events] == [
        "ChannelReady",
        # #24: what the room is doing, said before anything can change it, so a
        # room that opens and waits says so rather than saying nothing.
        "Attending",
        # #74: and how it is receiving the argument, on the same terms. A
        # safelight with no value would be the screen's ambient ground picking
        # its own colour until the first turn landed.
        "RoomTemperature",
        "AgentTranscript",
        "AgentFinished",
    ]


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
        floor=mid_room(),
    )

    events = await events_of(channel)

    assert model.said == ["Our gross margin is seventy percent."]
    assert [
        event.text for event in events if isinstance(event, AgentTranscript)
    ] == ["Seventy percent against a deck that says 61."]


async def test_the_room_says_when_the_floor_comes_back_to_the_presenter():
    """The turn is over, said out loud rather than left to be inferred.

    The room strictly alternates — one panel turn per finished utterance — so
    "the panelist stopped" really does mean "your turn". But nothing on the
    wire marks the end of an utterance, so a phone would have to guess it from
    a gap in arriving frames or a drained playback buffer. Both are guesses
    about the network: a two-second stall would tell the presenter to speak
    while a panelist is still mid-question, they would start, the panelist
    would resume, and the room would have manufactured an accidental barge-in.

    Last, and after the audio. A signal that the floor is free has to arrive
    behind the sound it follows, or the presenter is invited to talk over the
    end of the question.

    Deliberately NOT emitted when a turn is cancelled by barge-in: the
    presenter already holds the floor by having taken it, and being handed
    something you are standing on reads as the room losing track.
    """
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [Transcription(text="Our gross margin is seventy percent.", final=True)]
        ),
        model=ScriptedPanelModel(line="Against a deck that says 61."),
        grounding=Grounding(),
        floor=mid_room(),
    )

    events = await events_of(channel)

    spoke = [
        index for index, event in enumerate(events) if isinstance(event, AgentAudio)
    ]
    yielded = [
        index for index, event in enumerate(events) if isinstance(event, AgentFinished)
    ]

    assert len(yielded) == 1
    assert not spoke or yielded[0] > spoke[-1]


async def test_a_caption_names_the_archetype_who_composed_it():
    """Who spoke, carried with the words rather than left to be guessed.

    The composer already picks an archetype and speaks in its voice; until now
    that choice died here, and the phone received three identical rectangles
    and a line with no owner. `Product.md` §3.4 makes the active speaker part
    of the live interrogation surface, and the screen develops one tray per
    seated archetype — which it cannot do from text.

    Seated with one archetype so the assertion is about the name being *the
    one who spoke*, not about it being a plausible member of the room. With a
    full panel a broken implementation that always named the first seat would
    pass roughly a third of the time.

    The slug rather than a display name, matching `Session.archetypes` and the
    transcript's own `speaker` column. The phone resolves it against the
    archetype catalogue it already holds to offer the picker.
    """
    only = next(one for one in LIBRARY if one.name == "risk_officer")
    channel = OrchestratedChannel(
        panel=(only,),
        transcription=FakeTranscription(
            [Transcription(text="We have no exposure there.", final=True)]
        ),
        model=ScriptedPanelModel(line="No exposure, or none you have measured?"),
        grounding=Grounding(),
        floor=mid_room(),
    )

    events = await events_of(channel)

    assert [
        event.speaker for event in events if isinstance(event, AgentTranscript)
    ] == ["risk_officer"]


async def test_what_the_user_said_outlives_the_room():
    """The tracer bullet for persistence, and the half nothing else can supply.

    `UserSpoke` carries no text and `AgentTranscript` is deliberately only the
    panel (`events.py`), so the relay never learns a word the user said. This
    channel is the only object holding both sides — which is why the seam is
    here and not there.

    Without it the coach has nothing. `Product.md` §405 grounds debrief and
    sparring in the session's transcript, and `CLAUDE.md` requires that scope be
    structural rather than a system prompt: a coach that cannot see the
    transcript has no grounding to be constrained *to*.
    """
    transcript = FakeTranscript()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [Transcription(text="Our gross margin is seventy percent.", final=True)]
        ),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        transcript=transcript,
        floor=mid_room(),
    )

    await events_of(channel)

    assert Said(speaker=USER, text="Our gross margin is seventy percent.") in transcript.lines


async def test_a_challenge_is_kept_against_the_panelist_who_made_it():
    """Half a transcript is worse than none, and this is the half that grades.

    `Product.md` §3.5 ranks weak *answers*, which is a judgement about a pair —
    what was asked and what came back. A record of only the user's side cannot
    express it, and a coach reading one would be inventing the question.

    Attribution is the assertion, not merely presence. Sparring re-runs a
    specific panelist's challenge, and `CLAUDE.md` requires the archetype whose
    domain covers a metric to be the one that owns it — a line filed under the
    wrong name puts the Technical Skeptic's words in the CFO's mouth a week
    later.
    """
    transcript = FakeTranscript()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [Transcription(text="Our gross margin is seventy percent.", final=True)]
        ),
        model=ScriptedPanelModel(speaker="cfo", line="The deck says sixty-one."),
        grounding=Grounding(),
        transcript=transcript,
        floor=mid_room(),
    )

    await events_of(channel)

    # The pair, not the whole `Said`. Attribution is the claim here, and a line
    # carrying a new field it has no opinion about is not a regression in it.
    assert ("cfo", "The deck says sixty-one.") in [
        (line.speaker, line.text) for line in transcript.lines
    ]


class TakingTurns:
    """Hands the floor to a different archetype each time it is asked."""

    #: A different question every call. The same line from the same archetype
    #: twice is a repeat, and `agents/reasked.py` hands the floor away from a
    #: panelist that returns with one, which would test that instead of this.
    QUESTIONS = (
        "What did onboarding do to the cost of landing a customer?",
        "Who at those two customers will take a reference call?",
        "Where does the margin go once support is staffed?",
        "Which quarter does sponsorship have to renew in?",
    )

    def __init__(self, *speakers: str) -> None:
        self._speakers = list(speakers)
        self._next = 0
        self._written = 0

    async def select(self, *, candidates: Sequence[Archetype], context) -> ModelReply:
        speaker = self._speakers[min(self._next, len(self._speakers) - 1)]
        self._next += 1
        return ModelReply(text=speaker)

    async def compose(
        self, *, archetype: Archetype, context, finding=None, dispute=None
    ) -> ModelReply:
        question = self.QUESTIONS[self._written % len(self.QUESTIONS)]
        self._written += 1
        return ModelReply(text=question)


class WatchingTranscript(FakeTranscript):
    """Signals when the panel has spoken, so a test can wait rather than sleep.

    A sleep long enough to be reliable here is also long enough to pass against
    a channel that never wrote the second line at all.
    """

    def __init__(self) -> None:
        super().__init__()
        self.panel_spoke = asyncio.Event()

    async def record(self, line: Said, *, at: float | None = None) -> None:
        await super().record(line, at=at)
        if line.speaker != USER:
            self.panel_spoke.set()


async def test_a_disputing_line_is_recorded_as_one():
    """The flag has to survive the write, or the debrief cannot be fair.

    `PanelTurn.disputed` is already correct — #54's tests prove the gate and
    prove the turn carries what it decided. This is the next link: a turn that
    knew it was disputing, writing a line that does not say so.

    It would fail silently, which is what makes it worth a test. The room would
    behave identically, the transcript would read perfectly well, and the only
    symptom would appear a week later in a debrief telling somebody they ducked
    a question the CFO talked over — the exact accusation #56 exists to prevent.
    """
    transcript = WatchingTranscript()
    transcription = DrivenTranscription()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=transcription,
        # Three turns, not two. #81 added a gate: a panelist cannot claim its
        # priority outranks a colleague's before it has stated one, so the CFO
        # has to have spoken before it can dispute. The champion's domains
        # ("proof", "references") do not overlap the CFO's, which is what makes
        # the third turn eligible.
        model=TakingTurns("cfo", "champion", "cfo"),
        grounding=Grounding(),
        transcript=transcript,
        floor=mid_room(),
    )

    reader = asyncio.create_task(events_of(channel))

    # One utterance at a time, each answered before the next arrives. Two finals
    # fed together is barge-in: the second cancels the turn answering the first,
    # and there is never a colleague's line to take issue with.
    for said in (
        "Sponsorship is locked in.",
        "We rebuilt onboarding last quarter.",
        "Two customers have signed since.",
    ):
        transcript.panel_spoke.clear()
        transcription.feed(Transcription(text=said, final=True))
        await asyncio.wait_for(transcript.panel_spoke.wait(), timeout=1)

    transcription.hang_up()
    await asyncio.wait_for(reader, timeout=1)

    panel = [line for line in transcript.lines if line.speaker != USER]
    assert [(line.speaker, line.disputed) for line in panel] == [
        ("cfo", False),
        # Not the champion's turn: it has not spoken yet, so it has no stated
        # priority to rank above the CFO's (#81).
        ("champion", False),
        ("cfo", True),
    ]


async def test_words_spoken_through_a_cancelled_turn_are_still_kept():
    """Talking over the panel must not erase what you said.

    A second utterance cancels the turn answering the first — that is barge-in,
    and `orchestrated.py` is explicit that the user's line is recorded by the
    listener rather than by the turn precisely *"because this task can be
    cancelled and that must not depend on it."* The record has to inherit that
    property, or the transcript loses exactly the sentences a user was most
    insistent about.

    It is also the sharper half of a metering promise. A room that ends badly is
    still handed to the debrief, and a debrief missing the user's last words is
    reasoning about a room that did not happen.
    """
    transcript = FakeTranscript()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [
                Transcription(text="Margin is seventy percent.", final=True),
                Transcription(text="Well — closer to sixty.", final=True),
            ]
        ),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        transcript=transcript,
        floor=mid_room(),
    )

    await events_of(channel)

    said = [line.text for line in transcript.lines if line.speaker == USER]
    assert said == ["Margin is seventy percent.", "Well — closer to sixty."]


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
        floor=mid_room(),
    )

    events = await events_of(channel)

    assert model.composed_for == []
    assert not [event for event in events if isinstance(event, AgentTranscript)]


async def test_selection_runs_while_the_user_is_still_speaking():
    """The one hop that can leave the serial path, and the reason partials exist.

    Measured warm against live Gemini: selection 0.77s, composition 0.82s, VAD
    0.77s, first speech frame 0.38s — 2.74s, against the ~1.5s at which
    `CLAUDE.md` says the room stops feeling real, and matching the 2.70s
    measured end to end from a phone. Selection is the only term of the four
    that does not need the finished sentence: it wants the gist and the room, not
    the last word.

    So it starts on the first partial, while the user is still talking, and by
    the time they stop the answer is already in hand. `model.py` and
    `docs/panel-orchestration.md` have specified this since the two-call design
    was adopted — the diagram is in the doc — and `_listen` never did it, which
    is why the whole 0.77s was still being paid after the user went quiet.

    Waited for rather than slept past. A sleep long enough to be reliable is
    also long enough to pass against a channel that routes on the final.
    """
    model = ScriptedPanelModel()
    transcription = DrivenTranscription()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=transcription,
        model=model,
        grounding=Grounding(),
        floor=mid_room(),
    )

    reader = asyncio.create_task(events_of(channel))
    transcription.feed(Transcription(text="Our gross margin held at", final=False))
    await asyncio.wait_for(model.selecting.wait(), timeout=1)
    transcription.hang_up()
    await asyncio.wait_for(reader, timeout=1)

    assert model.routed_on == ["Our gross margin held at"]


async def test_the_finished_utterance_uses_the_speaker_already_chosen_for_it():
    """The payoff, and the thing that keeps the overlap free.

    Routing early only helps if the finished sentence then *uses* it. A room
    that re-routed on the final would have paid the 0.77s twice — once in the
    background where it was invisible, once on the critical path where it is the
    whole problem — and doubled the token cost of every turn to be slower than
    before.

    So: one selection for the utterance, made on the partial, and the archetype
    it named is the one that composes.
    """
    model = ScriptedPanelModel(speaker="technical_skeptic")
    transcription = DrivenTranscription()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=transcription,
        model=model,
        grounding=Grounding(),
        floor=mid_room(),
    )

    reader = asyncio.create_task(events_of(channel))
    transcription.feed(Transcription(text="We built the whole", final=False))
    await asyncio.wait_for(model.selecting.wait(), timeout=1)
    transcription.feed(
        Transcription(text="We built the whole pipeline ourselves.", final=True)
    )
    await asyncio.sleep(0.05)
    transcription.hang_up()
    await asyncio.wait_for(reader, timeout=1)

    assert model.routed_on == ["We built the whole"], "the room routed twice"
    assert model.composed_for == ["technical_skeptic"]
    # And composition still sees the finished sentence, not the fragment routing
    # worked from. Routing wants the gist; a challenge quotes what was said.
    assert model.said == ["We built the whole pipeline ourselves."]


async def test_a_selection_the_user_outran_does_not_hold_up_the_answer():
    """A short answer must not cost more than a long one.

    The overlap hides selection inside the utterance, which works while the
    utterance is longer than the call. It is not always: 0.77s of routing
    against a user who says *"about sixty"* and stops leaves the final arriving
    first. Waiting for it there would put the entire hop back on the critical
    path in exactly the case with the least room for it — and, worse, silently,
    since every measurement taken on a full sentence would look fine.

    So the room does not wait. Keyword routing is already the fallback for a
    selection that fails or names nobody (`routing.choose`, ~53% relevance), and
    a selection that was merely late is the same situation: it costs relevance
    rather than silence, which is the trade `panel.select_speaker` was written to
    make.
    """

    class NeverAnswers(ScriptedPanelModel):
        async def select(self, *, candidates, context) -> ModelReply:
            self.routed_on.append(context.said)
            self.selecting.set()
            await asyncio.Event().wait()  # a routing call that never returns
            raise AssertionError("unreachable")

    model = NeverAnswers()
    transcription = DrivenTranscription()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=transcription,
        model=model,
        grounding=Grounding(),
        floor=mid_room(),
    )

    reader = asyncio.create_task(events_of(channel))
    transcription.feed(Transcription(text="About", final=False))
    await asyncio.wait_for(model.selecting.wait(), timeout=1)
    transcription.feed(Transcription(text="About sixty.", final=True))
    await asyncio.sleep(0.05)
    transcription.hang_up()
    events = await asyncio.wait_for(reader, timeout=1)

    assert [event for event in events if isinstance(event, AgentTranscript)], (
        "the room waited for a selection instead of answering"
    )
    assert model.composed_for == ["cfo"], "keyword routing did not take over"


async def test_a_room_that_ends_mid_sentence_leaves_no_routing_call_running():
    """The cost of starting work early is having to stop it.

    Routing now begins on a partial, so there is a window — the length of an
    utterance — in which a room can end with a model call outstanding. The
    phone hanging up mid-sentence is the ordinary way that happens, not an
    exotic one.

    Left running it is a paid request nobody will read, holding a connection for
    a room that no longer exists — the same leak `open()` closes the
    transcription stream to prevent, and `_listen` is cancelled for. Python
    would also report it at interpreter exit, long after anything that could
    explain it is gone.
    """
    abandoned = asyncio.Event()

    class Interruptible(ScriptedPanelModel):
        async def select(self, *, candidates, context) -> ModelReply:
            self.selecting.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                abandoned.set()
                raise
            raise AssertionError("unreachable")

    model = Interruptible()
    transcription = DrivenTranscription()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=transcription,
        model=model,
        grounding=Grounding(),
        floor=mid_room(),
    )

    reader = asyncio.create_task(events_of(channel))
    transcription.feed(Transcription(text="Our gross margin", final=False))
    await asyncio.wait_for(model.selecting.wait(), timeout=1)

    # The phone goes away before the sentence is finished.
    transcription.hang_up()
    await asyncio.wait_for(reader, timeout=1)

    assert abandoned.is_set(), "the room closed with a model call still running"


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
        floor=mid_room(),
    )

    events = await events_of(channel)

    assert sequence(events) == [
        "ChannelReady",
        "UserSpoke",
        "AgentTranscript",
        # No speaker on this channel, so `Spent` still reports the model's
        # tokens and zero characters — nothing was synthesised to charge for.
        "Spent",
        # Nothing was played, but the turn is just as over and the phone still
        # has to know the floor came back.
        "AgentFinished",
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
        floor=mid_room(),
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
        async def compose(self, *, archetype, context, finding=None, dispute=None) -> ModelReply:
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
        async def compose(self, *, archetype, context, finding=None, dispute=None) -> ModelReply:
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
        floor=mid_room(),
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
        async def compose(self, *, archetype, context, finding=None, dispute=None) -> ModelReply:
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
        floor=mid_room(),
    )

    events = await events_of(channel)

    assert sequence(events) == [
        "ChannelReady",
        "UserSpoke",
        "AgentTranscript",
        # Before the audio, because both providers have already charged by the
        # time the first frame exists — see `_turn`.
        "Spent",
        "AgentAudio",
        "AgentAudio",
        # Last, behind the sound it follows. Announced any earlier and the
        # presenter is invited to talk over the end of the question.
        "AgentFinished",
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
        floor=mid_room(),
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
        floor=mid_room(),
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
        floor=mid_room(),
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


async def test_a_room_that_cannot_compose_ends_instead_of_billing_in_silence():
    """A dead panel model must not read as a thoughtful pause.

    The turn runs as a task beside the listener, and its exception was collected
    with `return_exceptions=True` and dropped. So a `ProviderUnavailable` from
    the composer produced a room that stayed open, kept the meter running, never
    spoke, and never told the relay anything was wrong — the user paying by the
    minute for silence, with no refund, because nothing had failed as far as the
    session was concerned.

    Surfaced through the event stream rather than logged, because the relay
    already knows what to do with it: end the room as a provider failure, which
    settles it and refunds the affected minutes. Nothing else in the pipeline
    needs to change.
    """

    class BrokenModel(ScriptedPanelModel):
        async def compose(self, *, archetype, context, finding=None, dispute=None) -> ModelReply:
            raise ProviderUnavailable(reason="panel_model_error")

    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [Transcription(text="Our margin is seventy percent.", final=True)]
        ),
        model=BrokenModel(),
        grounding=Grounding(),
        floor=mid_room(),
    )

    with pytest.raises(ProviderUnavailable):
        await events_of(channel)


async def test_a_panelist_cut_off_is_not_a_failure():
    """Cancellation is the product working, and must stay silent.

    Barge-in cancels a turn on every single interruption. If the guard above
    treated a `CancelledError` like any other exception, the first time a user
    talked over a panelist the room would end as a provider failure and refund
    them — turning the feature the product is built around into an outage.
    """
    transcription = DrivenTranscription()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=transcription,
        model=ScriptedPanelModel(),
        speaker=GatedSpeaker(),
        grounding=Grounding(),
        floor=mid_room(),
    )

    async def interrupt():
        transcription.feed(Transcription(text="Margin is seventy percent.", final=True))
        await asyncio.sleep(0.05)
        transcription.feed(Transcription(text="Well—", final=False))
        await asyncio.sleep(0.05)
        transcription.hang_up()

    events, _ = await asyncio.gather(events_of(channel), interrupt())

    assert any(type(event).__name__ == "Interrupted" for event in events)


async def test_a_room_says_it_is_alive_even_when_nobody_is_speaking():
    """Without this the reaper kills every room at forty-five seconds.

    `Heartbeat` is what the relay turns into `record_progress`, and the reaper
    orphans any active session whose progress mark is older than
    `ORPHAN_TIMEOUT` — three ticks, forty-five seconds. ElevenLabs Agents sent
    pings and the adapter translated them; owning the loop removed the vendor
    and took the heartbeat with it, so every orchestrated room was reaped
    mid-conversation, settled as a client disconnect, and the phone was told the
    room was over while the user was still talking to it.

    It is deliberately not conditional on anybody speaking. A user thinking for
    two minutes about a hostile question is in a live room; deciding otherwise
    is the idle timeout's job, on a separate clock the session owns, and
    conflating the two is what would make silence look like a dropped
    connection.
    """
    transcription = DrivenTranscription()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=transcription,
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        heartbeat_seconds=0.02,
        floor=mid_room(),
    )

    async def stay_quiet():
        await asyncio.sleep(0.05)
        transcription.hang_up()

    events, _ = await asyncio.gather(events_of(channel), stay_quiet())

    beats = [event for event in events if isinstance(event, Heartbeat)]
    assert len(beats) >= 2, "a quiet room must keep reporting that it is open"


class ScriptedClaimReader:
    """Answers with the figures a test declared for each utterance.

    Keyed by what was said rather than positional, because the room may read an
    utterance the test did not expect — and a positional script would silently
    hand it somebody else's figures rather than failing.
    """

    def __init__(self, script: dict[str, tuple]) -> None:
        self._script = script
        self.heard: list[str] = []

    async def read(self, *, said: str, known_metrics: tuple[str, ...] = ()) -> ClaimReading:
        self.heard.append(said)
        return ClaimReading(claims=self._script.get(said, ()))


def claim(metric: str, value: float, *, unit: Unit = Unit.PERCENT) -> QuantitativeClaim:
    return QuantitativeClaim(
        quote="spoken", metric=metric, value=value, unit=unit, period="Q3 2026"
    )


async def three_turns(model, reader, said: Sequence[str], transcript=None) -> None:
    """Run a room across several utterances, letting each turn finish first.

    Same pacing as `two_turns` and for the same reason — a script yielding every
    final in one tick is a user talking over the panel, which the channel is
    right to treat as barge-in. It also matters more here: the whole point is
    that a reading started on one utterance is collected on the next, and a test
    that delivered both at once would prove nothing about the ordering.
    """
    transcription = DrivenTranscription()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=transcription,
        model=model,
        grounding=Grounding(),
        auditor=Auditor(reader=reader),
        transcript=transcript,
        floor=mid_room(),
    )

    spoken = asyncio.Queue()

    async def collect():
        async for event in channel.events():
            if isinstance(event, AgentTranscript):
                spoken.put_nowait(event)

    reading = asyncio.create_task(collect())
    for utterance in said:
        transcription.feed(Transcription(text=utterance, final=True))
        await asyncio.wait_for(spoken.get(), timeout=1)
    transcription.hang_up()
    await asyncio.wait_for(reading, timeout=1)


class WatchingModel(ScriptedPanelModel):
    """Records the finding each composition was handed, in order."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.findings: list[object] = []

    async def compose(self, *, archetype, context, finding=None, dispute=None) -> ModelReply:
        self.findings.append(finding)
        return await super().compose(
            archetype=archetype, context=context, finding=finding
        )


async def test_a_contradiction_reaches_the_panel_on_the_turn_after_it_was_spoken():
    """Targeted interruption, wired — and deliberately one turn late.

    The Auditor reads figures out of an utterance with a model call measured at
    0.97s. Composition takes 0.82s and cannot begin until the finding exists,
    because the finding decides both who speaks and what they say — so waiting
    for it is not a 0.15s overlap but a full extra hop in series, taking the
    room from ~2.15s to ~3.1s and undoing the entire latency budget.

    Reading a partial instead, the way selection does, is worse rather than
    cheaper. Routing tolerates three words because prefix length was measured
    not to change the choice; a *figure* has no such tolerance — "sixty" against
    "sixty-one percent" is a different number, and a wrong number in a
    panelist's mouth is the one failure the extract/compute split exists to make
    impossible.

    So the reading starts when an utterance finishes and is collected when the
    next one does. That is not a compromise: between two finals there is a panel
    answer, the user thinking and the user talking — five to ten seconds — and
    0.97s disappears inside it. The catch routes the very next turn at no cost,
    and findings do not go stale, being about two fixed moments already past.
    """
    reader = ScriptedClaimReader(
        {
            "Our gross margin is sixty-one.": (claim("gross margin", 61),),
            "Margin is seventy percent.": (claim("gross margin", 70),),
        }
    )
    model = WatchingModel()
    await three_turns(
        model,
        reader,
        [
            "Our gross margin is sixty-one.",
            "Margin is seventy percent.",
            "And we are hiring twelve people.",
        ],
    )

    # Nothing to contradict on turn one; turn two's own contradiction is still
    # being read while that turn composes.
    assert model.findings[0] is None
    assert model.findings[1] is None

    caught = model.findings[2]
    assert caught is not None, "the catch never reached the panel"
    assert caught.domain == "margin"
    assert "61" in caught.summary and "70" in caught.summary


async def test_a_line_the_auditor_caused_is_recorded_as_one():
    """The only trace of a contradiction that outlives the room.

    Nothing persists a `Finding`. It is read from one utterance, routes the next
    turn, and is gone — so by the time a debrief opens, the fact that the Auditor
    caught something has to have been written down or it never happened.

    The routing reason is where it lives, because the alternative is a stored
    copy of the finding's summary sitting beside a panel line that already states
    the same contradiction in words the user heard (#45). Two versions of one
    fact, free to disagree.

    Asserted on the recorded line rather than on the turn: the turn is already
    known to be right — `test_a_contradiction_reaches_the_panel_on_the_turn_after
    _it_was_spoken` proves it — and a channel that knew and did not write it down
    would look identical from every other angle in this file.
    """
    reader = ScriptedClaimReader(
        {
            "Our gross margin is sixty-one.": (claim("gross margin", 61),),
            "Margin is seventy percent.": (claim("gross margin", 70),),
        }
    )
    transcript = FakeTranscript()

    await three_turns(
        WatchingModel(),
        reader,
        [
            "Our gross margin is sixty-one.",
            "Margin is seventy percent.",
            "And we are hiring twelve people.",
        ],
        transcript=transcript,
    )

    caused_by = [
        line.chosen_by for line in transcript.lines if line.speaker != USER
    ]
    assert caused_by == ["model", "model", "finding"]


async def test_a_slow_reading_never_stands_between_the_user_and_an_answer():
    """The property the whole one-turn-behind design exists to buy.

    A reading is a model call, and a model call can be slow or can hang. If the
    room waited for one the Auditor would sit directly on the critical path —
    the place the partial-transcript overlap was built to clear — and a
    background improvement would become the reason the panel is late.

    The scripted reader elsewhere in this file answers instantly, so it cannot
    show this: every reading is already finished by the time it is collected,
    and a version that waited would pass every other test here. Written after
    exactly that mutation survived.

    The reading is not cancelled, unlike a late routing call. A contradiction is
    about two fixed moments already in the past, so a slow one is not wrong —
    only later — and it is collected on a subsequent turn.
    """

    class NeverAnswers:
        def __init__(self) -> None:
            self.reading = asyncio.Event()

        async def read(self, *, said: str, known_metrics: tuple[str, ...] = ()) -> ClaimReading:
            self.reading.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    reader = NeverAnswers()
    model = WatchingModel()
    transcription = DrivenTranscription()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=transcription,
        model=model,
        grounding=Grounding(),
        auditor=Auditor(reader=reader),
        floor=mid_room(),
    )

    spoken = asyncio.Queue()

    async def collect():
        async for event in channel.events():
            if isinstance(event, AgentTranscript):
                spoken.put_nowait(event)

    reading = asyncio.create_task(collect())

    transcription.feed(Transcription(text="Our gross margin is sixty-one.", final=True))
    await asyncio.wait_for(spoken.get(), timeout=1)
    await asyncio.wait_for(reader.reading.wait(), timeout=1)

    # The second utterance must be answered while the first is still being read.
    transcription.feed(Transcription(text="Margin is seventy percent.", final=True))
    await asyncio.wait_for(spoken.get(), timeout=1), "the room waited for a reading"

    transcription.hang_up()
    await asyncio.wait_for(reading, timeout=1)

    assert model.findings == [None, None]


async def test_a_room_records_how_long_each_turn_took(caplog):
    """Open Risk #3 is measured in spikes and invisible in production.

    Every latency figure in `docs/panel-orchestration.md` came from a script on
    a laptop against a local server. A user on a phone experiences that plus the
    wire, and when they say the room felt slow there is nothing to say whether
    the panel was slow or the network was — which is the first question, and the
    one that decides whether the fix is ours at all.

    Timed from the finished utterance, because that is when the user stopped
    talking and started waiting. Ending at the caption rather than at the last
    audio frame: the caption is when the room has something to say, and
    synthesis streams over the length of an utterance, so measuring to the end
    would report the length of the answer rather than the wait for it.

    A number, never the line. `CLAUDE.md` forbids transcripts in logs.
    """
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [Transcription(text="Our gross margin is seventy percent.", final=True)]
        ),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        floor=mid_room(),
    )

    with caplog.at_level(logging.INFO):
        await events_of(channel)

    (timed,) = [r for r in caplog.records if r.getMessage() == "panel_turn_latency"]
    assert timed.context["seconds"] >= 0
    assert "text" not in timed.context and "line" not in timed.context


async def test_a_final_with_nothing_in_it_is_not_an_utterance():
    """The room stays quiet when the transcriber hands it nothing.

    Reported twice on a device. Once the panel opened with "Begin" after a long
    silence; once, after the presenter had actually spoken and waited, it said
    "You have said nothing. What is the cost per unit?" — which is the composer
    being handed an empty string and improvising a generic challenge out of it.

    `_listen` acted on `result.final` alone and never looked at the text, so an
    empty final did all four of the things a real utterance does: emitted
    `UserSpoke`, appended a `Said` to the transcript, ran the Auditor, and
    started a turn. Every one of those is wrong for a person who said nothing.

    The Auditor and the transcript matter as much as the turn. A blank line in
    `session_transcript_lines` is one the debrief will later rank a weak answer
    against, so an empty final does not merely produce one bad question — it
    corrupts the record the whole unmetered half is grounded in.
    """
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [
                Transcription(text="", final=True),
                Transcription(text="   ", final=True),
            ]
        ),
        model=ScriptedPanelModel(line="Against what basis?"),
        grounding=Grounding(),
        floor=mid_room(),
    )

    events = await events_of(channel)

    assert not [event for event in events if isinstance(event, AgentTranscript)]
    assert not [event for event in events if type(event).__name__ == "UserSpoke"]


async def test_a_users_line_is_stamped_where_they_started_not_where_they_stopped():
    """#69, and the reason a stamp taken at `record()` would not do.

    A user's line is written when the *final* lands, which is after they have
    stopped talking. Somebody who answered for ninety seconds would have every
    word of it filed at the moment they finished, and a player seeking there
    would land past the thing it was asked to play.

    The start is knowable without asking the vendor for anything: `_listen`
    already reads partials to run selection early, so the first partial since
    the last final *is* when this utterance began.
    """
    clock = ScriptedClock()
    transcript = FakeTranscript()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=TimedTranscription(
            clock,
            [
                (4.0, Transcription(text="Our gross", final=False)),
                (
                    11.5,
                    Transcription(
                        text="Our gross margin is seventy percent.", final=True
                    ),
                ),
            ],
        ),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        floor=mid_room(),
        transcript=transcript,
        clock=clock,
    )

    await events_of(channel)

    said = [(line, at) for line, at in transcript.stamped if line.speaker == USER]
    assert [at for _, at in said] == [4.0]


async def test_each_utterance_is_stamped_from_its_own_first_partial():
    """The marker is per utterance, not per room.

    Held once and never reset, every line in a twelve-minute room would carry
    the offset of the first thing anybody said — which is worse than no offset,
    because it is confidently wrong and looks like data.
    """
    clock = ScriptedClock()
    transcript = FakeTranscript()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=TimedTranscription(
            clock,
            [
                (4.0, Transcription(text="Our gross", final=False)),
                (11.5, Transcription(text="Our gross margin is seventy.", final=True)),
                (40.0, Transcription(text="Because the", final=False)),
                (52.0, Transcription(text="Because the deck is old.", final=True)),
            ],
        ),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        floor=mid_room(),
        transcript=transcript,
        clock=clock,
    )

    await events_of(channel)

    said = [at for line, at in transcript.stamped if line.speaker == USER]
    assert said == [4.0, 40.0]


async def test_a_final_with_no_partial_before_it_is_stamped_where_it_landed():
    """A transcriber that skipped straight to a final still gets an answer.

    Interim results are a requirement of the seam and the whole latency plan
    rests on them — but a vendor that emitted one final and nothing else would
    otherwise leave the marker unset, and an unstamped line on an account that
    can record is a hole in the record with no explanation attached to it.

    The final's own reading is the honest fallback: late by the length of the
    utterance, and never a guess about a moment nobody observed.
    """
    clock = ScriptedClock()
    transcript = FakeTranscript()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=TimedTranscription(
            clock,
            [(11.5, Transcription(text="Our gross margin is seventy.", final=True))],
        ),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        floor=mid_room(),
        transcript=transcript,
        clock=clock,
    )

    await events_of(channel)

    said = [at for line, at in transcript.stamped if line.speaker == USER]
    assert said == [11.5]


async def test_a_room_with_no_clock_files_its_lines_without_one():
    """The seam is optional, exactly like the transcript store beside it.

    A channel exercised without a relay has no mixer and therefore no clock,
    and it must still record a full transcript — null means "no anchor", which
    every reader already has to handle for the rooms that ran before this
    existed.
    """
    transcript = FakeTranscript()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [Transcription(text="Our gross margin is seventy.", final=True)]
        ),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        floor=mid_room(),
        transcript=transcript,
    )

    await events_of(channel)

    assert transcript.stamped
    assert all(at is None for _, at in transcript.stamped)


async def test_the_room_says_who_is_about_to_challenge_before_they_speak():
    """#75, and `Product.md` §3.4's second half — the first was speaker identity.

    The information exists earlier than the audio and nothing carried it. #42
    already runs selection against a partial while the presenter is still
    talking, so by the time they stop the floor is assigned; composition and
    synthesis then take a measured 0.82s and 0.38s before a word is audible.
    That gap is the whole feature.

    Ordered, not merely present. An announcement that arrived after its own
    caption would be a tray developing for somebody already speaking, which is
    the screen reporting the past.

    A partial before the final, because that is what makes the whole thing
    possible and what a real utterance always produces — `_route` starts from
    the first one, and without it there is nothing decided early to announce.
    """
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [
                Transcription(text="Our gross", final=False),
                Transcription(text="Our gross margin is seventy percent.", final=True),
            ]
        ),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        floor=mid_room(),
    )

    events = await events_of(channel)
    kinds = [type(event).__name__ for event in events]

    assert "Challenging" in kinds
    assert kinds.index("Challenging") < kinds.index("AgentTranscript")


async def test_who_was_announced_is_who_actually_speaks():
    """The one property that makes this worth shipping rather than dangerous.

    A tray that emerges and then does not speak has lied to somebody mid-argument
    — the reason #75 was split out of #41 rather than built with it. So the
    announcement is not a second guess at the speaker: it is read from the same
    rule `interrogate` applies, and a test compares the two rather than trusting
    that two spellings agree.
    """
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [
                Transcription(text="Our gross", final=False),
                Transcription(text="Our gross margin is seventy percent.", final=True),
            ]
        ),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        floor=mid_room(),
    )

    events = await events_of(channel)

    announced = [e.archetype for e in events if type(e).__name__ == "Challenging"]
    spoke = [e.speaker for e in events if isinstance(e, AgentTranscript)]
    assert announced == spoke


async def test_an_utterance_that_produced_no_partial_announces_nobody():
    """Silence rather than a guess, and it is a real case rather than a corner.

    `_route` starts from the first partial only. A final that arrives with none
    before it — a very short utterance, or a transcriber that endpointed
    straight to a commit — leaves nothing decided early, so `interrogate` routes
    inline as it always has and there is nothing true to announce yet.

    Announcing anyway would mean guessing, and a tray that develops for somebody
    who then does not speak is the failure this whole feature was split out of
    #41 to avoid. The room simply proceeds as it did before #75 existed.
    """
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(
            [Transcription(text="Our gross margin is seventy percent.", final=True)]
        ),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        floor=mid_room(),
    )

    events = await events_of(channel)

    assert not [e for e in events if type(e).__name__ == "Challenging"]
    # And the room still answers. The absence is of an announcement, never of a
    # turn — a silent tray must not cost the presenter a question.
    assert [e.speaker for e in events if isinstance(e, AgentTranscript)] == ["cfo"]


async def test_the_rooms_two_clocks_agree_about_what_time_it_is():
    """#98. Two counters answer "how far into the room are we", and must not drift.

    `RoomMixer.elapsed()` counts user samples in the relay and stamps
    `session_transcript_lines.began_at_seconds` (#69).
    `OrchestratedChannel._seconds_elapsed()` counts the same audio one call
    later, in `send_audio`, and stamps every Auditor finding — the same field
    also drives `_seconds_heard`, which is what METERS the room.

    The merge landed: with a clock injected, `_seconds_elapsed` reads it, so in
    a real room the two are one authority by construction. What this test now
    guards is the seam that remains — the byte-derived *fallback* a clockless
    channel uses must still value a frame exactly as the mixer does, or a room
    exercised without a relay stamps findings on a different scale than one
    with. No clock is injected here, deliberately: the fallback is the path
    under test.

    Fed directly rather than through a relay, because what is under test is the
    arithmetic rather than the wiring: the relay calling both on every frame is
    one line, and the thing that would rot is the two counters disagreeing about
    what a frame is worth.
    """
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription([]),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
    )
    mixer = RoomMixer()

    # Three and a bit seconds, in the frame size the phone actually sends.
    for _ in range(40):
        frame = b"\x01\x00" * 800
        mixer.heard(frame)
        await channel.send_audio(frame)

    assert int(mixer.elapsed()) == channel._seconds_elapsed()
    assert mixer.elapsed() > 0, "a clock that never moved agrees with anything"


async def test_a_findings_moment_reads_the_rooms_clock_when_one_is_keeping_time():
    """#98's merge — the finding and the line it points at share one authority.

    A finding's `at_seconds` exists so a panelist can put a moment to somebody
    and the debrief can seek there (#69) — and "there" is a position in the
    mixed recording, which is exactly what the injected `RoomClock` measures.
    Derived from `_heard_bytes` instead, it is the meter's number: the same
    value today, but a separate authority, free to drift the day a frame is
    dropped on one path and not the other.

    So with a clock keeping time, the finding reads it. The bytes remain the
    meter's business, untouched — and the fallback for a room with no relay
    behind it, which has no mixer and nothing better to offer.
    """
    clock = ScriptedClock()
    reader = ScriptedClaimReader(
        {"Our margin is seventy percent.": (claim("gross margin", 70.0),)}
    )
    auditor = Auditor(reader=reader)
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=TimedTranscription(
            clock,
            # The clock says 47.9 when the final lands; no audio ever reached
            # `send_audio`, so the byte counter still says zero. The stamp
            # tells us which one the finding believed.
            [(47.9, Transcription(text="Our margin is seventy percent.", final=True))],
        ),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        auditor=auditor,
        floor=mid_room(),
        clock=clock,
    )

    await events_of(channel)
    # The reading runs beside the loop and is collected on the *next* utterance
    # — there is none here, so settle it by hand before looking.
    if channel._reading is not None:
        await asyncio.wait_for(channel._reading, timeout=1)

    assert [spoken.at_seconds for spoken in auditor.heard] == [47]


class RollingPanelModel(ScriptedPanelModel):
    """A panel whose line changes each turn, so a test can tell them apart."""

    def __init__(self, lines: Sequence[str]) -> None:
        super().__init__()
        self._lines = list(lines)

    async def compose(self, *, archetype, context, finding=None, dispute=None) -> ModelReply:
        reply = await super().compose(
            archetype=archetype, context=context, finding=finding, dispute=dispute
        )
        del reply
        return ModelReply(text=self._lines.pop(0))


async def test_the_room_refuses_its_own_line_returning_into_the_gap():
    """#78. The panel's voice comes back up the microphone, alone, and is not
    the presenter.

    Room 066f32db: six of nine "user" lines were word-for-word repeats of the
    panelist immediately before them — the loudspeaker reaching the microphone
    in the gap after playback, where it is the only voice and therefore the
    primary speaker. Each one reset the idle clock, entered the transcript,
    and composed a turn: the room interrogating itself on the presenter's
    minutes, and the debrief later ranking weak answers against words nobody
    said.

    So a final that near-verbatim repeats the room's newest panel line does
    *nothing at all* — the same four refusals as the empty final above it,
    and for the same reason: a room must never answer something nobody said.
    """
    transcription = DrivenTranscription()
    transcript = FakeTranscript()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=transcription,
        model=ScriptedPanelModel(line="What specifically breaks at ten times the load?"),
        grounding=Grounding(),
        transcript=transcript,
        floor=mid_room(),
    )

    events: list = []
    spoken = asyncio.Queue()

    async def collect():
        async for event in channel.events():
            events.append(event)
            if isinstance(event, AgentTranscript):
                spoken.put_nowait(event)

    reader = asyncio.create_task(collect())
    transcription.feed(Transcription(text="Our margin is seventy percent.", final=True))
    await asyncio.wait_for(spoken.get(), timeout=1)
    # The line returns as the transcriber respells it — "ten" -> "10" is the
    # exact difference the measured room recorded.
    transcription.feed(
        Transcription(text="What specifically breaks at 10 times the load?", final=True)
    )
    transcription.hang_up()
    await asyncio.wait_for(reader, timeout=1)

    # Not in the record the debrief is grounded in.
    assert [line.text for line in transcript.lines if line.speaker == USER] == [
        "Our margin is seventy percent."
    ]
    # No turn was composed against it — one panel line in the whole room.
    assert len([e for e in events if isinstance(e, AgentTranscript)]) == 1
    # And the idle clock never heard it: UserSpoke is what the relay turns
    # into record_speech, and echo keeping an abandoned room alive past every
    # idle check is the runaway this guard exists to stop.
    assert len([e for e in events if type(e).__name__ == "UserSpoke"]) == 1


async def test_only_the_newest_panel_line_can_be_an_echo():
    """A match against anything older is a coincidence, not a loudspeaker.

    Echo returns in the gap right after playback — by the time another
    exchange has happened, the sound is long dead. A presenter who happens to
    say words matching a question from two turns ago is quoting it, which is
    speech, and the room owes them an answer.
    """
    transcription = DrivenTranscription()
    transcript = FakeTranscript()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=transcription,
        model=RollingPanelModel(
            [
                "What breaks at ten times the load?",
                "Where is that margin from?",
                "And who maintains it?",
            ]
        ),
        grounding=Grounding(),
        transcript=transcript,
        floor=mid_room(),
    )

    spoken = asyncio.Queue()

    async def collect():
        async for event in channel.events():
            if isinstance(event, AgentTranscript):
                spoken.put_nowait(event)

    reader = asyncio.create_task(collect())
    for utterance in [
        "Our ingest pipeline is the risk.",
        "The margin is from the Q3 audit.",
        # The first panel line, word for word — but two exchanges old, so the
        # newest panel line is "Where is that margin from?" and this matches
        # nothing that could still be in the air.
        "What breaks at ten times the load?",
    ]:
        transcription.feed(Transcription(text=utterance, final=True))
        await asyncio.wait_for(spoken.get(), timeout=1)
    transcription.hang_up()
    await asyncio.wait_for(reader, timeout=1)

    assert [line.text for line in transcript.lines if line.speaker == USER] == [
        "Our ingest pipeline is the risk.",
        "The margin is from the Q3 audit.",
        "What breaks at ten times the load?",
    ]


async def test_the_auditors_reading_is_counted_into_what_the_room_spent():
    """#14's first real datapoint exposed this: a grounded twelve-minute room
    recorded `auditor_invocations` 0, and the claim-reader's own docstring
    already suspected why — the Auditor accumulates its spend on itself
    (`Auditor.spent`, `Auditor.readings`) and nothing ever read either. Left
    uncounted, the observed dollars-per-minute understate exactly the rooms
    the Auditor works hardest in, which are the grounded rooms the wedge
    depends on.

    The reader's tokens fold into the llm columns — same vendor, same bill,
    priced by the same rate card — and the count gets its own field because
    §4.3 sized the table expecting one reading per utterance.
    """

    class PricedReader:
        async def read(self, *, said: str, known_metrics=()) -> ClaimReading:
            return ClaimReading(
                claims=(), usage=TurnUsage(input_tokens=200, output_tokens=8)
            )

    transcription = DrivenTranscription()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=transcription,
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        auditor=Auditor(reader=PricedReader()),
        floor=mid_room(),
    )

    async def feed():
        transcription.feed(Transcription(text="Margin is seventy percent.", final=True))
        await asyncio.sleep(0.05)
        transcription.feed(Transcription(text="And it holds at scale.", final=True))
        await asyncio.sleep(0.05)
        transcription.hang_up()

    events, _ = await asyncio.gather(events_of(channel), feed())

    spent = [event for event in events if isinstance(event, Spent)]
    assert sum(report.auditor_invocations for report in spent) == 2
    # The scripted model reports zero usage, so every llm token here is the
    # reader's — two readings of 200 in, 8 out.
    assert sum(report.llm_input_tokens for report in spent) == 400
    assert sum(report.llm_output_tokens for report in spent) == 16
