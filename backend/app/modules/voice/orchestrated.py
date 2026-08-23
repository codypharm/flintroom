"""A room we run ourselves.

ElevenLabs Agents hands a whole conversation to one remote agent, and that
cannot be a Flintroom panel. Turn-taking, the grounded challenge, targeted
interruption and — most of all — the rule that a composer sees exactly one
persona all live in `app/agents/`, and none of them exist inside somebody else's
conversational agent. A single agent wearing four names is the *"synthetic within
two minutes"* failure §3.3 exists to prevent.

So this satisfies the same `VoiceChannel` contract while owning the loop:
transcribe, decide who speaks, write their line. The relay cannot tell the
difference, which is what the seam was for — nothing in `relay.py` changes, and
the metering, idle detection and barge-in machinery built against the vendor
channel keeps working unmodified.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from app.agents.archetypes import Archetype
from app.agents.auditor import Auditor, ClaimReader
from app.agents.context import Finding, Grounding, Routed, Said, TurnContext, USER
from app.agents.difficulty import STANDARD_PRESSURE, Pressure
from app.agents.model import PanelModel, TurnUsage
from app.agents.opening import Chooser, NoOneToOpen, OpeningFloor, opener_from
from app.agents.panel import interrogate, select_speaker, who_takes_the_floor
from app.agents.routing import choose
from app.agents.closing import TimeCall, closer_from
from app.agents.silence import Silence, nudge_from
from app.agents.temperature import Temperature, temperature_of
from app.core.logging import get_logger
from app.modules.voice.events import (
    AgentAudio,
    Attending,
    Attention,
    AgentFinished,
    AgentTranscript,
    ChannelReady,
    Challenging,
    Heartbeat,
    Interrupted,
    RoomTemperature,
    Spent,
    UserSpoke,
    VoiceEvent,
)
from app.modules.voice.echo import hears_itself
from app.modules.voice.hearing import RoomHearing
from app.modules.voice.speech import Speaker
from app.modules.voice.clock import RoomClock
from app.modules.voice.transcript import TranscriptStore
from app.modules.voice.transcription import Transcriber, TranscriptionStream

log = get_logger(__name__, tag="voice")

#: How often a live room reports that it is still open.
#:
#: The reaper orphans any active session whose progress mark is older than
#: `ORPHAN_TIMEOUT` — three ticks, forty-five seconds — so this has to be
#: comfortably inside that. Ten seconds leaves room for a missed sweep and a
#: slow one without ever approaching the cutoff, and costs one small write.
#:
#: ElevenLabs Agents sent pings and the adapter translated them into
#: `Heartbeat`. Owning the loop removed the vendor and took the heartbeat with
#: it, and nothing failed loudly: rooms simply died at forty-five seconds,
#: settled as a user who had hung up, while somebody was still talking to them.
HEARTBEAT_SECONDS = 10.0

#: What the transcriber is billed against. The relay carries PCM16 at 16 kHz
#: mono in both directions, so a second of audio is a fixed number of bytes and
#: needs no clock to measure.
SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2


class OrchestratedProvider:
    """Opens rooms we run ourselves. **One instance per room, not per process.**

    That is the one way this differs from the vendor agent it replaced, and it
    follows from an asymmetry rather than from taste. Theirs needed no arguments
    to `open()` because which agent, what persona and what voice all lived on
    their dashboard; they already knew. Ours has to be told which archetypes
    are seated and which deck to attack, and both are per-session facts in our
    database.

    Resolved at construction rather than by widening `VoiceProvider.open()`. The
    shared seam stays untouched and the relay keeps knowing nothing about decks.
    It is also the call `CLAUDE.md` already makes for audit actors — context
    bound when the service is built, never passed per call — for the same
    reason: a caller that could name the room per call could name a different
    one halfway through.

    `app/modules/voice/room.py` is what builds one from a session id. `speaker`
    stays optional because a silent panel is a legitimate deployment — it still
    transcribes, routes, composes and captions — while a panel that cannot be
    exercised without a synthesis vendor is not.
    """

    def __init__(
        self,
        *,
        panel: Sequence[Archetype],
        transcriber: Transcriber,
        model: PanelModel,
        speaker: Speaker | None = None,
        opener_speaker: Speaker | None = None,
        grounding: Grounding | None = None,
        reader: ClaimReader | None = None,
        transcript: TranscriptStore | None = None,
        clock: RoomClock | None = None,
        pressure: Pressure = STANDARD_PRESSURE,
        audience: str = "",
    ) -> None:
        #: Who is seated, in seat order. Public because a room's roster is a
        #: fact about the room rather than an implementation detail of it — the
        #: factory that assembles one is judged on exactly this, and captions
        #: will eventually need to name whoever is speaking.
        self.panel = panel
        #: How hard this room pushes — #55's rung, resolved from the account at
        #: assembly. Public for the reason `panel` is: it is a fact about the
        #: room rather than an implementation detail, and it is what a caller
        #: checks to know which room it got.
        self.pressure = pressure
        #: What the presenter said about the room they are walking into, or
        #: empty. #66, and public on the same reasoning as `pressure` above: it
        #: is a fact about the room rather than an implementation detail of it,
        #: and a caller checking which room it got has no other way to see it.
        #:
        #: A `str` rather than `str | None`, converted once at `build_room`. The
        #: composer branches on truthiness, and a nullable value here would put
        #: that branch one missing `is not None` away from fencing the word
        #: None and handing it to a live room.
        self.audience = audience
        self._transcriber = transcriber
        self._model = model
        self._speaker = speaker
        self._opener_speaker = opener_speaker
        self._grounding = grounding
        # The reader is process-wide and stateless; the `Auditor` built around
        # it is neither, so it is made per stream in `open()` rather than here.
        self._reader = reader
        # Per room, like the panel and the grounding, and for the same reason:
        # it is bound to one session. Unlike the `Auditor` it is *not* rebuilt
        # per stream — it holds the room's ordinal counter, and a fresh one would
        # restart at zero and collide with the lines already written.
        self._transcript = transcript
        # #69. The relay's mixer, read rather than driven — this side only ever
        # asks it what time it is. Optional on exactly the terms the transcript
        # store is: a channel exercised without a relay has no mixer, records a
        # full transcript, and files every line with no offset.
        self._clock = clock

    @asynccontextmanager
    async def open(self) -> AsyncIterator[OrchestratedChannel]:
        """Dial the transcriber and build a room around it.

        The stream closes on every path out, including the failing ones — which
        are the only ones that ever leak. An open transcription stream is a room
        still running on somebody's invoice with nobody in it.
        """
        async with self._transcriber.open() as transcription:
            yield OrchestratedChannel(
                panel=self.panel,
                transcription=transcription,
                model=self._model,
                speaker=self._speaker,
                opener_speaker=self._opener_speaker,
                grounding=self._grounding,
                pressure=self.pressure,
                audience=self.audience,
                # A fresh one per stream, never shared. An `Auditor` accumulates
                # every figure spoken in a session, so a reused one would open
                # the next room already holding the last user's numbers — and
                # would then accuse somebody of contradicting a claim they never
                # made, quoting it verbatim in a panelist's voice. A correctness
                # failure and a privacy one in the same object.
                auditor=Auditor(reader=self._reader) if self._reader else None,
                transcript=self._transcript,
                clock=self._clock,
            )


class OrchestratedChannel:
    """One interrogation, driven turn by turn.

    Holds the transcript twice, for two different lifetimes. The list in memory
    is what each turn is grounded in and dies with the room. The `TranscriptStore`
    is what outlives it, and `docs/session-retention.md` settles what that means:
    text for the life of the account on every tier, because the debrief is
    grounded in it and `Product.md` §405 makes that a precondition rather than a
    feature.

    This is the only object holding **both sides** of the room. `UserSpoke`
    carries no text and `AgentTranscript` is deliberately only the panel, so the
    relay — where every other per-session write happens — never learns a word the
    user said. That asymmetry is why the seam is here.
    """

    def __init__(
        self,
        *,
        panel: Sequence[Archetype],
        transcription: TranscriptionStream,
        model: PanelModel,
        speaker: Speaker | None = None,
        grounding: Grounding | None = None,
        auditor: Auditor | None = None,
        transcript: TranscriptStore | None = None,
        clock: RoomClock | None = None,
        pressure: Pressure = STANDARD_PRESSURE,
        audience: str = "",
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
        floor: OpeningFloor | None = None,
        choose: Chooser | None = None,
        opener_speaker: Speaker | None = None,
    ) -> None:
        self._panel = panel
        # Stamped on every `TurnContext` this channel builds. Defaulted to the
        # room that ships today so the many tests that construct a channel
        # directly keep describing the room `scripts/rotation.py` measured.
        self._pressure = pressure
        # Fixed for the room, like the claims below and unlike the transcript —
        # #66, the presenter's own note about who they are facing. Stamped on
        # every `TurnContext` alongside `pressure` for the same reason: both are
        # true of the whole room, and a turn that saw a different one would be a
        # turn from a different room.
        #
        # Empty by default so every channel constructed directly — the spikes,
        # the older tests — keeps describing the room that shipped before this.
        self._audience = audience
        # Optional, like the speaker and the auditor: a room still runs without
        # somewhere to file its words, and every test that is not about
        # persistence should not have to supply one. Production always does —
        # without it the debrief has nothing to be grounded in.
        self._transcript_store = transcript
        # #69. Optional on exactly the same terms as the store above: a room
        # without one still records a full transcript, and files every line with
        # no offset — null means "no anchor", which every reader already handles
        # for the rooms that ran before this existed.
        self._clock = clock
        #: Where the room was when the current utterance began, or None between
        #: utterances — #69, and the reason a stamp taken at `record()` will not
        #: do. A user's line is written when the *final* lands, which is after
        #: they stopped: somebody who answered for ninety seconds would have
        #: every word of it filed at the moment they finished, and a player
        #: seeking there lands past the thing it was asked to play.
        #:
        #: Nothing is asked of the vendor for this. `_listen` already reads
        #: partials to start selection early, so the first partial since the
        #: last final *is* when this utterance began.
        self._began_at: float | None = None
        # Optional, like the speaker: a room without one still transcribes,
        # routes, composes, speaks and captions. What it loses is the panel
        # catching a figure that moved.
        self._auditor = auditor
        # The reading of the utterance just finished, and the catch left over
        # from the one before it. See `_audit`.
        self._reading: asyncio.Task[Finding | None] | None = None
        # Injectable so a test can watch several beats without waiting for
        # them. The default is the only value production uses.
        self._heartbeat_seconds = heartbeat_seconds
        self._transcription = transcription
        self._model = model
        # Optional so the room can be exercised — and read in a transcript —
        # without a synthesis vendor attached. A silent panel is a legitimate
        # development configuration; a panel that cannot be tested without one
        # is not.
        self._speaker = speaker
        # The opener's voice, and the only line in the room allowed to be slow.
        # #34: v3 performs audio tags and costs 0.39s to first byte — which an
        # interrogation turn cannot afford and a line spoken into silence can.
        # Falls back to the ordinary speaker, so losing it costs the opener its
        # texture rather than its existence.
        self._opener_speaker = opener_speaker or speaker
        # The claims stay fixed for the room; only the transcript grows. Both are
        # rebuilt into a fresh `Grounding` each turn because it is frozen, which
        # is what stops a turn in flight seeing a reference set that moved under
        # it.
        self._claims = grounding.claims if grounding else ()
        self._transcript: list[Said] = list(grounding.transcript) if grounding else []
        # Audio forwarded to the transcriber, and how much of it has already
        # been reported. Two counters rather than one because a turn reports
        # whole seconds and the bytes do not arrive in second-sized pieces —
        # subtracting what was reported is what stops the remainder being lost
        # on every turn, which would undercount a chatty room the most.
        self._heard_bytes = 0
        self._charged_seconds = 0
        # Selection for the utterance currently being spoken, started on its
        # first partial and collected when it finishes. One per utterance, never
        # one per partial: a partial arrives every ~150ms, so routing on each
        # would be twenty model calls for a sentence and turn the cheapest hop
        # in the turn into the most expensive thing in the room.
        self._routing: asyncio.Task[Routed] | None = None
        # How many turns in this room have opened by taking issue with a
        # colleague. Counted here because the cap is per room and nothing else
        # has that lifetime — `interrogate` sees one turn, and the transcript
        # cannot say which lines disputed because a disputing line and an
        # ordinary one are the same shape.
        self._disputes = 0
        # #79. The stretch at the start where nobody interrupts. Defaulted
        # rather than optional, because a room without one is the room that
        # attacked an empty transcript and invented its subject — that is not a
        # configuration a deployment should be able to choose by omission.
        self._floor = floor if floor is not None else OpeningFloor()
        # Injected so `scripts/rotation.py` and the suite can pin who opens and
        # with which line. A room that cannot be repeated cannot be measured.
        self._choose = choose
        # Set whenever the presenter says something while the floor is open, so
        # `_hold_the_floor` can rearm its settle timer instead of guessing.
        # An event rather than a timestamp: the waiter has to be *woken*, and a
        # value it would have to poll for is the same bug with more code.
        self._spoke = asyncio.Event()
        # The turn in flight. An attribute rather than a local in `_listen`,
        # because the floor closing can start one too and both have to be able
        # to cancel whatever the other left running — a barge-in that only
        # `_listen` knew about would talk over the opening challenge.
        self._speaking: asyncio.Task | None = None
        # The last value put on the queue, so a transition does not repeat
        # itself. Never read as the truth — `_attention` is the truth, and this
        # only decides whether saying it again is worth a message.
        self._attended: Attention | None = None
        # #74. The band the phone was last told, which is what the hysteresis
        # reads — a room already losing needs a clear window to leave, and one
        # that is convinced cools on the first catch.
        #
        # Not a cached reading. `temperature_of` derives the band from lines
        # already written every time it is asked, so nothing here can be
        # stranded by a turn that dies; this only holds which side of the
        # threshold the room was on, and the resting value is the honest place
        # to start from — a panel opens unconvinced.
        self._warmth: Temperature = Temperature.SKEPTICAL
        # #24. Whether this stretch of quiet has earned its one question, and
        # whether it got it. Changes nothing about the clock — see `Silence`.
        self._silence = Silence()
        # The room calling time on itself as the session cap nears, once. The
        # meter still owns the money and the close; this only decides whether
        # the ending gets said before it happens. The clock starts here rather
        # than at the cap's own anchor (the active span, on Postgres' clock) —
        # the two are seconds apart at most, and CALL_BEFORE_SECS absorbs it.
        self._time = TimeCall()
        self._opened_at = time.monotonic()
        # What the Auditor's reader has already been reported as spending.
        # `Auditor` accumulates totals on itself and, until 2026-08-23,
        # nothing ever read them — the column stayed zero in every session
        # and the first real cost datapoint (#14) understated exactly the
        # grounded rooms. Each `Spent` carries the delta since the last one.
        self._auditor_reported = TurnUsage()
        self._auditor_readings_reported = 0
        # When the room last heard them, on the same monotonic clock the floor
        # uses. Set at the open so a presenter who never speaks is still asked.
        self._heard_at = time.monotonic()
        # #77. Whether a voice has ever reached this room at all — a different
        # question from `_heard_at`, which measures the gap since the last one
        # and cannot tell a first gap from a broken microphone.
        self._ears = RoomHearing()

    async def _keep(self, line: Said, *, at: float | None) -> None:
        """File one line where it will outlive the room, if anywhere.

        Paired with every `self._transcript.append`, because the room's own
        memory and the record it leaves behind must hold the same thing — a line
        the panel is shown but that never reaches the debrief is a contradiction
        the coach cannot see and cannot be told about.

        `at` is passed rather than read here, and that is #69's whole shape: the
        two sides of the room are stamped from different moments, and only the
        caller knows which. A panel line is composed at the moment it belongs
        to; a user's line is written when their final arrives, which is the end
        of what they said rather than the start.
        """
        if self._transcript_store is None:
            return
        await self._transcript_store.record(line, at=at)

    def _at(self) -> float | None:
        """Where the room is now, or None if nothing is keeping time."""
        return None if self._clock is None else self._clock.elapsed()

    async def send_audio(self, pcm: bytes) -> None:
        """Straight through to the transcriber.

        No buffering and no voice-activity decision here. Endpointing is a thing
        transcribers are good at and this module would be bad at, and doing it in
        two places is how the two disagree about when the user stopped.

        Counted on the way past, because this is what the transcriber is paid
        for. Wall-clock room time is what the *user* is charged; bytes actually
        forwarded is what the vendor charges us, and the two differ exactly when
        a phone reconnects or a stream stalls.
        """
        self._heard_bytes += len(pcm)
        # Here rather than in `_listen`, because a transcriber that has decided
        # this is not speech reports nothing at all — which is precisely the
        # room #77 is about. These are the bytes the provider is given and bills
        # for, so nothing downstream of it can disagree with what it saw.
        self._ears.heard(pcm)
        await self._transcription.send_audio(pcm)

    def _seconds_heard(self) -> int:
        """Whole seconds of audio not yet reported, and mark them reported."""
        heard = self._heard_bytes // (SAMPLE_RATE * BYTES_PER_SAMPLE)
        unreported = heard - self._charged_seconds
        self._charged_seconds = heard
        return unreported

    async def events(self) -> AsyncIterator[VoiceEvent]:
        """Everything the room has to say, while it keeps listening.

        **Two concurrent halves, and the concurrency is the feature.** The first
        version of this read a transcription result, answered it, and only then
        read the next — which cannot be interrupted, because while a panelist is
        speaking nothing is listening. The user talking over them was not ignored
        so much as unheard until they had finished, and a panelist who concedes
        the floor after completing their sentence is not being interrupted.

        So a listener task reads transcription continuously and a turn runs
        beside it, joined by a queue. Cancelling the turn is what stops a
        panelist mid-word: `Speaker.speak` streams, so dropping the iteration
        drops the utterance, and nothing needs a cancel call that could leave an
        adapter half-spoken.
        """
        # First, and before anything is transcribed. This is what the relay turns
        # into `activate()`, which opens the billable interrogation span — a
        # channel that never sent one would leave a room the user can hear and
        # talk to, that the ledger believes never started, holding their
        # one-session lock until the reaper swept it.
        #
        # It reports that the channel exists, not that anybody has used it. A
        # user silent for the first thirty seconds is in a room that opened, and
        # the idle timeout is what decides otherwise.
        yield ChannelReady()

        out: asyncio.Queue[VoiceEvent | BaseException | None] = asyncio.Queue()

        # Before anything is transcribed, and never composed. #79: the opener is
        # spoken at the one moment the room holds nothing at all — no
        # transcript, and possibly no material — which is the exact condition
        # under which a model invents its subject. It is also what makes the
        # floor legible on a phone lying face-up on a desk, where the screen's
        # own "the room is listening" cannot be seen.
        # Before the opener, so there is never a window in which the phone has
        # heard the room speak but does not know what it is doing.
        await self._attend(out)
        # #74, on the same terms. The safelight *is* the screen's ambient
        # ground, so a room that opened without one would have the ground
        # picking its own colour until the first turn landed — on the one
        # surface whose premise is that nobody looks directly at it.
        await self._read_the_room(out, always=True)

        await self._open_the_room(out)

        listener = asyncio.create_task(self._listen(out))
        beating = asyncio.create_task(self._beat(out))
        holding = asyncio.create_task(self._hold_the_floor(out))
        try:
            while (event := await out.get()) is not None:
                if isinstance(event, BaseException):
                    # A turn that failed. Raised here rather than logged and
                    # dropped, because the relay already knows what to do with
                    # it — end the room as a provider failure, which settles and
                    # refunds. Swallowing it left the meter running on a room
                    # that would never speak again.
                    raise event
                yield event
        finally:
            # The consumer may stop early — the relay cancels this side whenever
            # the phone hangs up first. Without this the listener survives its
            # own room, holding a transcription stream open on somebody's
            # invoice with nobody reading it.
            listener.cancel()
            beating.cancel()
            # Ordinarily already finished: the floor closes on the first settle.
            # Cancelled anyway for the room that ends before anybody spoke, where
            # it would otherwise sit out the whole ninety-second cap.
            holding.cancel()
            await asyncio.gather(
                listener, beating, holding, return_exceptions=True
            )

    async def _open_the_room(
        self, out: asyncio.Queue[VoiceEvent | BaseException | None]
    ) -> None:
        """Hand the presenter the floor, out loud, in somebody's voice.

        **No model call.** The line comes from `Archetype.openers`, written by
        hand, and that is the point rather than an optimisation: this is spoken
        before a single word has been transcribed, so a composer asked for it
        would be composing from nothing — which is precisely the failure #79
        exists to remove. It also keeps the room's first sound off the critical
        path of a vendor round trip.

        Emitted through the same three events an ordinary turn uses, so the
        relay, the mixer, the recording and the phone all treat it as what it
        is: a panelist speaking. Nothing downstream needed a new case.

        A floor handed over already closed opens nothing. That is not a
        production state — `OrchestratedProvider.open` builds a fresh
        `OpeningFloor` for every room — but it is what lets a test describe the
        room *after* its opening without also re-describing the opening, and it
        keeps that affordance honest rather than hidden behind a second flag.

        A room whose panel has nothing to open with still opens — silently, and
        logged. That is only reachable with a panel seated entirely from custom
        archetypes, and losing the opener is a far smaller harm than refusing a
        metered room the user has already paid to enter.
        """
        if not self._floor.open:
            return

        try:
            who, line = (
                opener_from(self._panel, choose=self._choose)
                if self._choose is not None
                else opener_from(self._panel)
            )
        except NoOneToOpen:
            log.warning("room_opened_in_silence")
            return

        await out.put(AgentTranscript(line, speaker=who.name))
        if self._opener_speaker is not None:
            async for pcm in self._opener_speaker.speak(text=line, voice=who.voice):
                await out.put(AgentAudio(pcm))
            # The synthesiser was paid for this line like any other. The
            # hand-written paths were the last unpaid speech in the room —
            # found closing out the first §4.3 reconciliation, where every
            # room under-reported by its own greeting.
            await out.put(Spent(tts_characters=len(line)))
        await out.put(AgentFinished())

    async def _hold_the_floor(
        self, out: asyncio.Queue[VoiceEvent | BaseException | None]
    ) -> None:
        """Wait out the opening statement, then let the panel in.

        Two clocks, and they answer different questions. Until anything has been
        said the only thing that can end the floor is the **cap** — somebody
        collecting their thoughts for twenty seconds has not finished, and a
        settle pause measured from an empty room would fire before they drew
        breath. Once they have started, each thing they say rearms the
        **settle**, so the pauses inside a sentence do not read as the end of
        one. That distinction is the whole bug: finals commit after 0.7s, and
        nobody speaks in 0.7-second units.

        Woken by an event rather than polling a timestamp. The waiter has to be
        *woken*; a value it would have to check on a schedule is the same
        mechanism with a worse resolution and more code.
        """
        if not self._floor.open:
            return

        opened = time.monotonic()

        while True:
            left = self._floor.cap - (time.monotonic() - opened)
            if left <= 0:
                break
            # Nothing to settle until they have started. See above.
            wait = (
                self._floor.wait_for(elapsed=time.monotonic() - opened)
                if self._floor.words
                else left
            )
            self._spoke.clear()
            try:
                await asyncio.wait_for(self._spoke.wait(), timeout=wait)
            except TimeoutError:
                break

        await self._close_the_floor(out)

    async def _close_the_floor(
        self, out: asyncio.Queue[VoiceEvent | BaseException | None]
    ) -> None:
        """The panel's room now. Open the questioning against what was said.

        The turn is composed against the **whole** opening rather than the last
        fragment of it — `_answer` takes one `said`, and grounding a room's
        first challenge in the tail of a sentence is how it ends up about the
        wrong thing.

        A thin opening travels as a fact on the context, never as an
        instruction: `TurnContext.thin_opening`. What that earns is the
        composer's to decide, which is the discipline `weakness.py` holds for
        the same reason.
        """
        opening = self._floor.close()
        log.info("opening_floor_closed", words=self._floor.words, thin=opening.thin)

        self._speaking = await self._restart(
            self._speaking,
            opening.text,
            out,
            # Deliberately unrouted. Selection normally overlaps the tail of an
            # utterance, and here the tail was minutes ago — `interrogate`
            # chooses fresh, seeing the whole opening rather than a guess made
            # from its first partial.
            None,
            await self._take_finding(),
            thin_opening=opening.thin,
        )
        await self._attend(out)

    async def _ask_if_anybody_is_there(
        self, out: asyncio.Queue[VoiceEvent | BaseException | None]
    ) -> None:
        """Say something once the quiet has run long enough. #24.

        **Spoken, because the person this is for cannot see the screen.** They
        have turned away to find a figure, or left the room, or are holding a
        dead microphone. `docs/voice-stream-protocol.md` records the rest of the
        reasoning; the short version is that a visual warning arrives at the
        moment attention is lowest, aimed at somebody who by definition stopped
        looking.

        **Which question, decided by whether the room has ever heard them.**
        #77. Every line in `nudges` asks the presenter to speak, and to the
        third person on that list — the one holding a dead microphone — that is
        the room telling them to keep doing what has already failed. It reads as
        a room that is not listening, which is the failure this whole area keeps
        arriving back at. So a room that has heard nothing at all asks from
        `unheard` instead, and sends them to the handset.

        **It changes nothing.** No clock is reset and no limit is extended: the
        room still ends at `IDLE_LIMIT` and still refunds in full. A warning
        that bought time would be a second clock, and a silent room could then
        run forever on somebody's invoice.

        Nothing is said while a panelist is already speaking. A room that
        interrupted its own question to ask whether anybody was listening would
        be answering itself, which is the shape of every bug this file has had.
        """
        if self._speaking is not None and not self._speaking.done():
            return
        if not self._silence.worth_asking(
            quiet_for=time.monotonic() - self._heard_at
        ):
            return

        try:
            heard = not self._ears.unheard
            who, line = (
                nudge_from(self._panel, choose=self._choose, heard=heard)
                if self._choose is not None
                else nudge_from(self._panel, heard=heard)
            )
        except NoOneToOpen:
            log.warning("nobody_could_ask")
            self._silence.asked()
            return

        self._silence.asked()
        # `heard` says which of the two questions was asked, and it is the only
        # record of it — the line itself is never logged, because `CLAUDE.md`
        # forbids room speech in logs. A room that asked the wrong one is
        # otherwise indistinguishable in a trace from one that asked the right
        # one, which is exactly how this went unnoticed until #77.
        log.info("asked_if_anybody_is_there", archetype=who.name, heard=heard)

        # The same three events an ordinary turn uses, so the relay, the mixer,
        # the recording and the phone all treat it as what it is: a panelist
        # speaking. The caption is its own visual rendering, for free — no
        # second vocabulary, and the two can never disagree.
        #
        # Not filed in the transcript. It is not a challenge, the debrief must
        # not rank it, and `weakness._opening_statement` counts the presenter's
        # opening from the first panel line — which this would silently move.
        await out.put(AgentTranscript(line, speaker=who.name))
        if self._opener_speaker is not None:
            async for pcm in self._opener_speaker.speak(text=line, voice=who.voice):
                await out.put(AgentAudio(pcm))
            # The synthesiser was paid for this line like any other. The
            # hand-written paths were the last unpaid speech in the room —
            # found closing out the first §4.3 reconciliation, where every
            # room under-reported by its own greeting.
            await out.put(Spent(tts_characters=len(line)))
        await out.put(AgentFinished())

    async def _call_time_if_due(
        self, out: asyncio.Queue[VoiceEvent | BaseException | None]
    ) -> None:
        """Say the room is ending, before the meter ends it.

        The architect's room hit the session cap at 12:12 mid-sentence and it
        read as a malfunction — a meeting ends, a call drops, and the whole
        difference is one spoken line. The meter is untouched: it still closes
        and settles at `SESSION_LIMIT` exactly as before, so this line changes
        what the ending feels like and nothing about what it costs.

        **After whoever is speaking, never over them** — the architect's
        second constraint, and the same floor discipline the nudge above
        holds. A panelist mid-line defers it to the next beat; a presenter
        mid-flow does too, read as a gap in what the room has heard shorter
        than a breath. If the presenter talks clean through the final margin,
        the call is never made — there is no moment to make it in, and
        interrupting to announce the end would be the drop this exists to
        soften.
        """
        if self._speaking is not None and not self._speaking.done():
            return
        # A breath, not a silence: long enough that a comma does not count as
        # the floor being free, far too short for the idle machinery to care.
        if time.monotonic() - self._heard_at < 2.0:
            return
        if not self._time.worth_calling(elapsed=time.monotonic() - self._opened_at):
            return

        try:
            who, line = (
                closer_from(self._panel, choose=self._choose)
                if self._choose is not None
                else closer_from(self._panel)
            )
        except NoOneToOpen:
            # Marked as called even though nothing was said: a room that
            # cannot say it once cannot say it on the next beat either, and
            # retrying would log the same warning every ten seconds to the
            # end of the room.
            self._time.called()
            log.warning("nobody_could_call_time")
            return

        self._time.called()
        log.info("time_called", archetype=who.name)

        # The same three events an ordinary turn uses — relay, mixer,
        # recording and captions all treat it as a panelist speaking — and,
        # like the nudge, deliberately not filed in the transcript: it is not
        # a challenge, and the debrief must not rank it.
        await out.put(AgentTranscript(line, speaker=who.name))
        if self._opener_speaker is not None:
            async for pcm in self._opener_speaker.speak(text=line, voice=who.voice):
                await out.put(AgentAudio(pcm))
            # The synthesiser was paid for this line like any other. The
            # hand-written paths were the last unpaid speech in the room —
            # found closing out the first §4.3 reconciliation, where every
            # room under-reported by its own greeting.
            await out.put(Spent(tts_characters=len(line)))
        await out.put(AgentFinished())

    def _attention(self) -> Attention:
        """What the room is doing with the floor, worked out rather than recalled.

        **Nothing stores this**, which is the whole point. A remembered state is
        stranded by the paths that fail — a turn that dies would leave the room
        claiming to be working for the rest of the session, and a confidently
        wrong screen is worse than the silence it replaced. Derived, there is no
        transition to miss and nothing to clear.

        One function, two callers. The heartbeat and the transition points must
        never disagree about the same instant, and they cannot if neither of
        them decides anything.

        Deliberately silent about a panelist speaking: the caption and
        `AgentFinished` already carry that, and a second source for one fact is
        the bug that took a panelist off the screen mid-sentence.
        """
        if self._speaking is not None and not self._speaking.done():
            return Attention.WORKING
        if self._floor.open and self._floor.words:
            return Attention.HEARD
        # #77. Below the two above it, because both mean somebody has been
        # heard — a panelist answering them, or the floor holding what they
        # said — and this can only ever be true of a room that has heard
        # nothing. The ordering is therefore belt and braces rather than a
        # tie-break: `RoomHearing` latches off on the first non-zero sample.
        if self._ears.unheard:
            return Attention.UNHEARD
        return Attention.LISTENING

    async def _attend(
        self,
        out: asyncio.Queue[VoiceEvent | BaseException | None],
        *,
        always: bool = False,
    ) -> None:
        """Say what the room is doing, if it is worth saying.

        `always` is the heartbeat, and the difference matters. Transitions are
        sent for speed and de-duplicated, because a room repeating itself on
        every buffer would be noise; the heartbeat is sent for correctness and
        repeats deliberately, because suppressing it would leave a phone that
        dropped one message wrong for the rest of the room.

        The de-duplication is an optimisation and never a source of truth — it
        can cost a redundant message and never a missed one.
        """
        state = self._attention()
        if always or state is not self._attended:
            self._attended = state
            await out.put(Attending(state))

    async def _read_the_room(
        self,
        out: asyncio.Queue[VoiceEvent | BaseException | None],
        *,
        always: bool = False,
    ) -> None:
        """Say how the panel is receiving the argument, if it has changed.

        The same discipline as `_attend`, and for the same two reasons.
        Transitions go out immediately, because the safelight is the screen's
        ambient ground and a lag in it is a lag in the only signal a hands-free
        presenter perceives without looking. The heartbeat repeats whatever is
        true, because suppressing it would leave a phone that dropped one
        message showing the wrong room for the rest of the session.

        **The band is remembered; the reading is not.** `_temperature` is a pure
        function of lines already written, so there is no state to be stranded
        by a turn that dies — and `_warmth` exists only as the previous band the
        hysteresis needs, which is a fact about what the phone was last told
        rather than a claim about the room.
        """
        state = temperature_of(self._transcript, was=self._warmth)
        if always or state is not self._warmth:
            self._warmth = state
            await out.put(RoomTemperature(state))

    async def _beat(self, out: asyncio.Queue[VoiceEvent | BaseException | None]) -> None:
        """Report that the room is open, until it is not.

        On a clock rather than on activity, because that is what the event
        means: the channel is still delivering, not that anybody is
        participating. A user thinking for two minutes about a hostile question
        is in a live room, and deciding otherwise belongs to the idle timeout —
        a separate clock the session owns, fed by `UserSpoke`. Conflating them
        would make silence indistinguishable from a dropped connection, which is
        exactly the distinction the two events exist to keep apart.
        """
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            await out.put(Heartbeat())
            # Unconditional, and that is the safety net. See `_attend`.
            await self._attend(out, always=True)
            # Beside the attention and on the same terms: repeated deliberately,
            # because a phone that dropped the one transition message would
            # otherwise show the wrong room for the rest of the session.
            await self._read_the_room(out, always=True)
            # On the beat that already exists rather than on a timer of its
            # own. Ten seconds of resolution is ample for a sixty-second
            # threshold, and a second clock is a second thing to get wrong.
            await self._ask_if_anybody_is_there(out)
            # On the same beat and the same terms: only when the floor is
            # free, and at ten-second resolution against a thirty-second
            # margin.
            await self._call_time_if_due(out)

    async def _listen(self, out: asyncio.Queue[VoiceEvent | BaseException | None]) -> None:
        """Read transcription forever; start, and stop, turns as it goes."""
        try:
            async for result in self._transcription.results():
                if result.final:
                    # #69. Taken *and cleared* before the empty check below, so
                    # the marker belongs to exactly one utterance. Held across
                    # a dropped final it would stamp the next thing somebody
                    # said with the moment they started the thing that was
                    # discarded — a wrong answer that looks like data.
                    began = self._began_at
                    self._began_at = None

                    # **Nothing said is not an utterance.** Acting on `final`
                    # alone let an empty result do all four things a real one
                    # does: reset the idle clock, enter the transcript, wake the
                    # Auditor, and start a turn. Every one is wrong for somebody
                    # who said nothing, and on a device it produced a panelist
                    # announcing "You have said nothing. What is the cost per
                    # unit?" — the composer handed an empty string and
                    # improvising a generic challenge from it.
                    #
                    # The transcript matters as much as the turn. A blank line
                    # in `session_transcript_lines` is one the debrief later
                    # ranks a weak answer against, so an empty final does not
                    # merely ask one bad question: it corrupts the record the
                    # whole unmetered half is grounded in.
                    #
                    # **This is the fix, and #77 established there is no
                    # other one.** The trigger is sustained digital silence:
                    # measured across three rooms, the transcriber takes in
                    # 36-37 seconds of it and then commits one empty utterance.
                    # Not sending that silence was the obvious remedy and it
                    # does not work — `docs/echo-cancellation.md` measured a
                    # *quiet room* on this product's shipped audio
                    # configuration reading exact digital zero, so gating
                    # silence would gate every pause, which is the signal the
                    # transcriber endpoints on.
                    #
                    # So the empty final gets dropped here, and the presenter is
                    # told at twenty-five seconds that nothing has reached the
                    # room — see `hearing.py` and `Attention.UNHEARD`. This
                    # belongs here whatever the provider does, because a room
                    # must never answer something nobody said.
                    if not result.text.strip():
                        log.info("empty_final_ignored")
                        continue

                    # #78. The panel's own voice, returned by the loudspeaker
                    # into the gap after playback, where it is the only sound
                    # and therefore transcribed as the presenter. Measured
                    # narrow (`docs/echo-cancellation.md`): mixed under a
                    # talking presenter it is already rejected unaided, so the
                    # only line that can be echo is the *newest* panel line,
                    # and only while nothing genuine has been said since —
                    # which is exactly "the transcript still ends with it".
                    #
                    # Refused the same way as the empty final above, and for
                    # the same reason: a room must never answer something
                    # nobody said. No idle-clock reset either — on a handset
                    # with weak AEC, an abandoned room would otherwise keep
                    # itself alive past every idle check, asking and hearing
                    # its own questions on the presenter's minutes.
                    #
                    # The figures and never the text: transcript content is
                    # barred from logs, so these numbers are the only trace of
                    # why a line was refused an operator will ever see.
                    last = self._transcript[-1] if self._transcript else None
                    if last is not None and last.speaker != USER:
                        returning = hears_itself(last.text, result.text)
                        if returning.is_echo:
                            log.info(
                                "echo_final_refused",
                                matched=returning.matched,
                                novel=returning.novel,
                                coverage=round(returning.coverage, 3),
                            )
                            continue

                    # Before the turn is even started. This is what the relay
                    # turns into `record_speech`, and it is the only thing that
                    # resets the idle clock — panel speech deliberately does not.
                    # Emitting it after composition would leave that clock
                    # running across the slowest part of the turn, so a user who
                    # thought for eighty seconds and then answered would be
                    # reaped while the panel was replying to them.
                    await out.put(UserSpoke())
                    # They are here. The next stretch of quiet starts fresh, so
                    # somebody who steps away twice in one room is asked twice.
                    self._heard_at = time.monotonic()
                    self._silence.heard()
                    # #77. Words, so the microphone is proven — and the screen
                    # can never claim nothing has reached the room while the
                    # transcript is filling with what they said.
                    self._ears.spoke()
                    # Recorded here rather than inside the turn, because the turn
                    # can be cancelled and this must not be. A user who keeps
                    # talking through the panel's answer has still said the thing
                    # they said; losing it would erase their words from the room's
                    # memory because *we* chose not to reply to them, and the next
                    # selection would then judge an answer it never saw.
                    said = Said(speaker=USER, text=result.text)
                    self._transcript.append(said)
                    # Where they *started*, from the first partial of this
                    # utterance. The final's own reading is the fallback for a
                    # transcriber that emitted no partial at all — late by the
                    # length of what was said, and never a guess about a moment
                    # nobody observed.
                    await self._keep(said, at=began if began is not None else self._at())

                    # **The floor is still theirs.** #79: everything above this
                    # line keeps running through the opening — the transcript
                    # fills, the idle clock resets, the Auditor is fed — and
                    # only the turn is held back. A version that paused the
                    # whole room would cost the debrief its grounding and the
                    # panel its best catch, which are the two things the
                    # opening statement exists to create.
                    if self._floor.open:
                        self._floor.heard(result.text)
                        self._audit(result.text)
                        # Wakes `_hold_the_floor` so it rearms rather than
                        # closing on a pause the presenter has already ended.
                        self._spoke.set()
                        await self._attend(out)
                        continue

                    # Collected before the new one starts, so this turn is
                    # answered with the catch from the *previous* utterance and
                    # never waits for its own. See `_audit`.
                    finding = await self._take_finding()
                    self._audit(result.text)
                    self._speaking = await self._restart(
                        self._speaking,
                        result.text,
                        out,
                        await self._take_routing(result.text),
                        finding,
                    )
                    await self._attend(out)
                    continue

                # #69. The first partial since the last final is when this
                # utterance began, and it is the only observation of that moment
                # anywhere in the room. Set once and left alone: every later
                # partial of the same utterance is the same person still
                # talking, and overwriting would walk the stamp forward to
                # wherever they happened to stop.
                if self._began_at is None:
                    self._began_at = self._at()

                # The user is mid-sentence, and this is where the latency budget
                # is actually won. Selection measures 0.77s warm and wants the
                # gist rather than the last word, so it starts here and runs
                # underneath the rest of the utterance — by the time they stop,
                # the floor has already been assigned and only composition and
                # speech stand between silence and an answer.
                self._route(result.text)

                # If somebody is speaking they lose the floor now rather than at
                # the end of the user's line — waiting for the *final* would mean
                # waiting for the user to finish before conceding, which is a
                # panelist talking over them for three seconds and then stopping
                # politely.
                if self._speaking is not None and not self._speaking.done():
                    self._speaking = await self._stop(self._speaking)
                    # Synthesis runs ahead of playback, so frames the panelist
                    # will never reach are already buffered on the phone.
                    # Stopping only what we have not sent yet lets them talk over
                    # the person who just cut in.
                    await out.put(Interrupted())

            # The stream closed while the presenter still held the floor —
            # they made their case and nothing had answered it yet. Closing here
            # means an opening statement is always answered, whatever ended the
            # room, rather than being silently discarded because the socket
            # happened to go first.
            #
            # **Only if they actually said something.** A room that ends having
            # heard nothing must not compose anything — that is #77's rule, and
            # answering an empty opening is the same failure wearing a new
            # shape: a panelist challenging a statement nobody made.
            if self._floor.open and self._floor.words:
                await self._close_the_floor(out)

            # The stream closed. A turn still in flight is the room's last word,
            # and dropping it would lose a line the user was owed.
            if self._speaking is not None:
                await asyncio.gather(self._speaking, return_exceptions=True)
        finally:
            # A selection started on a partial the user never finished. There is
            # no turn left to hand it to, so it is a paid request nobody will
            # read holding a connection open for a room that has ended — the
            # same leak `open()` closes the transcription stream to prevent.
            if self._routing is not None:
                self._routing.cancel()
                await asyncio.gather(self._routing, return_exceptions=True)
                self._routing = None
            await out.put(None)

    def _route(self, said: str) -> None:
        """Start choosing a speaker for the utterance in progress, once.

        Fire-and-collect: the task is picked up by `_take_routing` when the
        utterance finishes. Started from the first partial only, so the room
        pays for exactly one selection per turn — the same number it paid
        serially, moved earlier rather than added to.

        **The first partial, not a fuller one.** It carries two or three words,
        which looks far too thin to route on and measured as not mattering:
        against live Gemini with a fixed roster and a growing transcript, three
        words and twelve words produced the same distribution of speakers, and
        the finished sentence barely moved it either. What concentrates turns on
        one archetype is a bias in the selection prompt that is present at every
        prefix length, and predates this — `docs/panel-orchestration.md` has the
        table. Waiting for more words would buy nothing measurable and spend the
        headroom that makes the overlap work.

        A known bound, left rather than engineered around: an utterance whose
        final never arrives — discarded by VAD, or dropped as a repeat by
        `ElevenLabsTranscriptionStream` — leaves its decision here for the next
        utterance to use. That costs one turn a choice made from slightly stale
        words, self-corrects on the following final, and is bounded by the same
        fallback a late selection already takes.

        The transcript is snapshotted now rather than read later, for the reason
        `_answer` rebuilds `Grounding` each turn: it is frozen, and a routing
        call reading a list that grew underneath it would be selecting against a
        room that no longer exists.
        """
        if self._routing is not None:
            return

        context = TurnContext(
            said=said,
            grounding=Grounding(claims=self._claims, transcript=tuple(self._transcript)),
            pressure=self._pressure,
            audience=self._audience,
            # This is the whole point of routing early, and until now the prompt
            # was never told. Selection here runs on a prefix of a sentence
            # still being spoken; the rule that presses an unanswered question
            # cannot tell that from an evasion, because neither contains a
            # figure, a name, a date or a mechanism.
            unfinished=True,
        )
        # A count, never the text. `CLAUDE.md` forbids transcripts in logs, and
        # this is the one number that says whether routing had anything to work
        # with — a selection made on three words is a selection made on nothing,
        # and it fails by quietly sending every turn to the same archetype
        # rather than by erroring.
        log.info("panel_routing_started", words=len(said.split()))
        self._routing = asyncio.create_task(
            select_speaker(self._panel, context=context, model=self._model)
        )

    def _audit(self, said: str) -> None:
        """Start reading the figures out of the utterance that just finished.

        **Deliberately one turn behind, and it costs nothing.** A reading is a
        model call measured at 0.97s warm, and composition — 0.82s — cannot
        begin until the finding exists, because a finding decides both who
        speaks and what they say. Waiting for it is therefore not an overlap but
        a whole extra hop in series, taking the room from ~2.15s to ~3.1s and
        undoing the entire latency budget.

        Reading a *partial* instead, the way selection does, is worse rather
        than cheaper. Routing tolerates three words because prefix length was
        measured not to change the choice; a figure has no such tolerance —
        "sixty" against "sixty-one percent" is a different number, and a wrong
        number in a panelist's mouth is the one failure the extract/compute
        split exists to make impossible.

        So it runs in the gap that already exists. Between two finished
        utterances there is a panel answer, the user thinking and the user
        talking — five to ten seconds — and 0.97s disappears inside it. The
        catch routes the very next turn at no cost, and findings do not go
        stale: they are about two fixed moments already in the past.
        """
        if self._auditor is None:
            return
        self._reading = asyncio.create_task(
            self._auditor.listen(said, at_seconds=self._seconds_elapsed())
        )

    def _seconds_elapsed(self) -> int:
        """How far into the room this utterance was.

        The injected `RoomClock` when one is keeping time — #98. A finding's
        moment exists so a panelist can put a second to somebody and the debrief
        can seek there (#69), and "there" is a position in the mixed recording,
        which is exactly what the clock measures. It is also the authority that
        stamps `began_at_seconds` on the line the finding is about, so the two
        cannot disagree by construction rather than by coincidence.

        The bytes are the fallback, not a second opinion: a channel with no
        relay behind it has no mixer, and audio actually forwarded is the best
        it can say. Metering (`_seconds_heard`) stays on the bytes either way —
        what a user is charged is not this method's question.
        """
        if self._clock is not None:
            return int(self._clock.elapsed())
        return self._heard_bytes // (SAMPLE_RATE * BYTES_PER_SAMPLE)

    async def _take_finding(self) -> Finding | None:
        """Collect the previous utterance's catch, if it is ready.

        Never waits, for the reason `_take_routing` never waits: this sits
        between the user stopping and the room answering. A reading that has not
        finished is left running and collected on the turn after — it is not
        wasted, only later — because a contradiction is about two fixed moments
        and does not expire.
        """
        if self._reading is None or not self._reading.done():
            return None

        reading, self._reading = self._reading, None
        try:
            return reading.result()
        except Exception:
            # `Auditor.listen` already swallows its own provider failures, so
            # anything arriving here is a bug rather than an outage. It still
            # must not end a live metered room — the Auditor is an improvement
            # to a session that works without it — but `CLAUDE.md` refuses to
            # let an unexpected exception become invisible, so the traceback is
            # logged in full rather than reduced to a type name. A swallowed
            # bug with no stack is one nobody can fix.
            log.exception("audit_failed")
            return None

    async def _take_routing(self, said: str) -> Routed | None:
        """Collect the selection started during this utterance, and clear it.

        **Only if it has already finished.** Waiting would put the whole 0.77s
        back between the user stopping and the room answering, which is the
        thing this exists to remove — and it would do it worst on short answers,
        where an utterance is over before the call returns and there is least
        patience to spare. Every measurement taken on a full sentence would
        still look fine, so the regression would be invisible.

        `None` sends `interrogate` to `routing.choose`, which is what a failed
        or unrecognised selection already falls through to: a late one costs
        relevance rather than silence, and in a live metered room a pause with
        nobody in it is the failure a user notices first.

        The cancelled call is not free — the provider may well have charged for
        it — but a cancelled request returns nothing to read a token count off,
        so it goes unrecorded. That undercounts, which is the safe direction to
        be wrong in and is recorded here so §4.3 knows to expect it.

        Cleared whatever happens, so the next partial starts a fresh one. Left
        in place, one routing decision would be reused for the rest of the room
        and the same archetype would answer everything.
        """
        routing, self._routing = self._routing, None
        if routing is None:
            # No partial ever arrived, so nothing was started to be late. Left
            # for `interrogate` to route the old way — a transcriber that emits
            # only finals loses the overlap, which is a latency cost, and must
            # not also silently lose model routing, which would be a quality one
            # nothing in a transcript could distinguish from bad luck.
            return None
        if not routing.done():
            routing.cancel()
            # Collected rather than abandoned, for the reason `_stop` gives: a
            # cancelled task nobody awaits is reported at interpreter exit, long
            # after the context that would explain it is gone.
            await asyncio.gather(routing, return_exceptions=True)
            log.info("panel_routing_outrun")
            # Keywords, decided here rather than by returning `None`. `None`
            # would send `interrogate` to `model.select` — starting a second
            # copy of the call just abandoned, this time squarely on the
            # critical path, so an utterance too short to hide one selection
            # would pay for two in series. `routing.choose` costs nothing and
            # answers immediately.
            return Routed(
                choose(
                    self._panel,
                    TurnContext(
                        said=said,
                        grounding=Grounding(
                            claims=self._claims, transcript=tuple(self._transcript)
                        ),
                        pressure=self._pressure,
                        audience=self._audience,
                    ),
                ),
                "fallback",
            )
        return routing.result()

    async def _restart(
        self,
        speaking: asyncio.Task | None,
        said: str,
        out: asyncio.Queue[VoiceEvent | BaseException | None],
        routed: Routed | None,
        finding: Finding | None,
        thin_opening: bool = False,
    ) -> asyncio.Task:
        """Begin a turn, abandoning one already running.

        A final arriving while a panelist speaks means the user talked over them
        and finished a sentence. The `Interrupted` for that was already sent on
        the partial that opened it, so this only has to stop the work.
        """
        if speaking is not None and not speaking.done():
            await self._stop(speaking)

        # #75. Before the turn, which is the entire feature: composition and
        # synthesis take a measured 0.82s and 0.38s, and this is what fills that
        # gap on a screen whose premise is that nobody is looking directly at it.
        #
        # After the abandonment above rather than before it, so a barge-in
        # cannot announce a challenger for a turn that is being thrown away.
        #
        # Read from `who_takes_the_floor`, the same call `interrogate` makes, so
        # the tray that develops and the voice that arrives cannot disagree.
        # Silent when nothing decided the floor early — no finding and no
        # partial to have routed on — because the alternative is a guess, and a
        # tray that emerges for somebody who never speaks has lied to a
        # presenter mid-argument.
        taking = who_takes_the_floor(self._panel, finding=finding, routed=routed)
        if taking is not None:
            await out.put(Challenging(archetype=taking.archetype.name))

        return asyncio.create_task(
            self._turn(said, out, routed, finding, thin_opening=thin_opening)
        )

    @staticmethod
    async def _stop(speaking: asyncio.Task) -> None:
        speaking.cancel()
        # Awaited rather than abandoned, for the reason the relay gives: a
        # cancelled task nobody collects is reported at interpreter exit, long
        # after the context that would have explained it is gone.
        await asyncio.gather(speaking, return_exceptions=True)
        return None

    async def _turn(
        self,
        said: str,
        out: asyncio.Queue[VoiceEvent | BaseException | None],
        routed: Routed | None = None,
        finding: Finding | None = None,
        thin_opening: bool = False,
    ) -> None:
        """One archetype's answer, from selection through to the last frame.

        Failures are put on the queue rather than allowed to die with the task.
        This runs beside the listener and its result is collected with
        `return_exceptions=True`, so anything raised here used to vanish — and a
        composer that had stopped answering produced a room that stayed open,
        kept billing, and never spoke again. Silence is indistinguishable from a
        slow model to somebody whose phone is face-down on a desk.

        Cancellation is deliberately not caught. Barge-in cancels a turn on
        every interruption, and treating that as a failure would end the room
        and refund the user the first time they talked over a panelist.
        """
        try:
            await self._answer(said, out, routed, finding, thin_opening=thin_opening)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Type only. A panelist's line quotes ingested material and
            # `CLAUDE.md` forbids that in logs; an exception's message may carry
            # whatever it was handed.
            log.warning("panel_turn_failed", error=type(exc).__name__)
            await out.put(exc)

    async def _answer(
        self,
        said: str,
        out: asyncio.Queue[VoiceEvent | BaseException | None],
        routed: Routed | None = None,
        finding: Finding | None = None,
        thin_opening: bool = False,
    ) -> None:
        started = time.monotonic()
        turn = await interrogate(
            self._panel,
            said=said,
            model=self._model,
            grounding=Grounding(
                claims=self._claims, transcript=tuple(self._transcript)
            ),
            pressure=self._pressure,
            audience=self._audience,
            # Already decided, during the sentence that just finished. Without
            # one — an utterance that produced no partial, or a routing call the
            # final overtook — `interrogate` chooses here as it always has.
            routed=routed,
            # The Auditor's catch from the previous utterance, if it found one.
            # It outranks `routed` inside `interrogate`: a specific contradiction
            # against specific figures is a better reason to hand somebody the
            # floor than a guess made from half a sentence.
            finding=finding,
            # The room's own tally. `interrogate` sees one turn and cannot know
            # what this room has already spent, so the bound would not exist if
            # the count stayed here unpassed — silently, because every turn on
            # its own would still look correct.
            disputes_spent=self._disputes,
            # Only ever true on a room's first turn — the presenter stopped
            # without saying what this is about. A fact, not an instruction.
            thin_opening=thin_opening,
        )

        # Recorded before the line is spoken, so that a panelist cut off two
        # words in is still on record as having asked. The next selection has to
        # know the question was put — otherwise a user who talks over the CFO
        # hears the same challenge again, which reads as a room that is not
        # listening rather than one that was interrupted.
        #
        # The user's own line was recorded by the listener, not here, because
        # this task can be cancelled and that must not depend on it.
        # `disputed` travels onto the line because the debrief reads the
        # transcript and not the turn. Once written, a line that took issue with
        # a colleague's priorities is indistinguishable from any other panel line
        # following panel text — so the question it moved the room off would look
        # exactly like one the presenter ducked, and #56 would tell them so.
        # `chosen_by` for the same reason: a finding is read from one utterance,
        # routes one turn, and is gone. Nothing persists it, so the routing
        # reason on this line is the only surviving evidence that the Auditor
        # caught the answer before it — which is what `weakness.py` reads to rank
        # a contradiction above a panelist's mere dissatisfaction.
        asked = Said(
            speaker=turn.archetype.name,
            text=turn.line,
            disputed=turn.disputed,
            chosen_by=turn.chosen_by,
        )
        self._transcript.append(asked)
        # #69. Where the room has reached *now*, which is a beat before this
        # line is audible: the caption goes on the socket ahead of its own
        # audio, and synthesis has not started. So a panel line's offset is
        # early by the synthesis latency.
        #
        # That is not residual error, it is the measurement. The gap between a
        # user line's offset and the next panel line's *is* the turn latency,
        # taken on the server — which Open Risk #3 has had no way to read except
        # from the client's own caption clock, on a dev build somebody is
        # holding. Erring early is also the forgiving direction for a seek:
        # landing a beat before a question beats landing inside it.
        #
        # The alternative was stamping where its audio actually lands, which is
        # exact and means writing the line and then updating it — a second write
        # to an append-only table, on the hot path of a live room, from a task
        # that does not own the line.
        await self._keep(asked, at=self._at())

        # **The only line that can move it**, and read here rather than on every
        # attention change: the band is a function of panel lines, so deriving
        # it when the presenter starts or stops speaking would ask the same
        # question of the same list and answer it the same way.
        #
        # With the caption rather than after the audio, so the ground and the
        # words move together — the caption goes out ahead of its own speech
        # already, and a safelight that shifted a sentence later would read as
        # the screen reacting to something the presenter had stopped hearing.
        #
        # After the append, so this line counts. A turn cut off by barge-in is
        # still on record as having been asked, which is exactly the case where
        # the read must not quietly revert.
        await self._read_the_room(out)

        if turn.disputed:
            self._disputes += 1

        # From the user going quiet to the room having something to say. The
        # only number that tells an operator whether a slow room was slow here
        # or slow on the wire — every latency figure in
        # `docs/panel-orchestration.md` was measured on a laptop against a local
        # server, and a phone adds a network nobody can see from a spike.
        #
        # `chosen_by` travels with it because the two explain each other: a turn
        # that fell back to keyword routing is one where the model was late, and
        # a slow turn with `chosen_by=model` is a slow composer instead.
        log.info(
            "panel_turn_latency",
            seconds=round(time.monotonic() - started, 2),
            chosen_by=turn.chosen_by,
            archetype=turn.archetype.name,
        )

        # The caption first, then the audio it captions. Synthesis streams over
        # the length of an utterance, so a client waiting for the last frame
        # before displaying the line would caption the room seconds late — and
        # captions are in the v1 accessibility floor, not a garnish on the audio.
        await out.put(AgentTranscript(turn.line, speaker=turn.archetype.name))

        # Reported before synthesis rather than after it, and that ordering is
        # the whole reason this is not a `finally`. A panelist cut off two words
        # in was still composed in full and still handed to the synthesiser in
        # full — both providers have already charged — so a turn that reports
        # only what the user heard would undercount precisely the interrupted
        # rooms, which is the barge-in the product is built around.
        # The Auditor's spend rides the same report, as a delta since the
        # last turn. A reading that completes after the room's final turn goes
        # unreported — bounded at one call, and preferable to a second event
        # type for a tail nobody else would carry.
        audited_in = audited_out = readings = 0
        if self._auditor is not None:
            audited_in = self._auditor.spent.input_tokens - self._auditor_reported.input_tokens
            audited_out = self._auditor.spent.output_tokens - self._auditor_reported.output_tokens
            readings = self._auditor.readings - self._auditor_readings_reported
            self._auditor_reported = self._auditor.spent
            self._auditor_readings_reported = self._auditor.readings

        await out.put(
            Spent(
                stt_seconds=self._seconds_heard(),
                llm_input_tokens=turn.usage.input_tokens + audited_in,
                llm_output_tokens=turn.usage.output_tokens + audited_out,
                tts_characters=len(turn.line) if self._speaker else 0,
                auditor_invocations=readings,
            )
        )

        if self._speaker is not None:
            async for pcm in self._speaker.speak(
                text=turn.line, voice=turn.archetype.voice
            ):
                await out.put(AgentAudio(pcm))

        # After the last frame, and deliberately not in a `finally`. Barge-in
        # cancels this task, and a cancelled turn must not announce the floor:
        # the presenter already took it, and handing somebody something they are
        # standing on reads as a room that has lost track of who is speaking.
        # A `finally` would do exactly that on every interruption.
        #
        # A room with no synthesiser reaches here too. It played nothing, but
        # the turn is just as over, and the phone still needs to know.
        await out.put(AgentFinished())
