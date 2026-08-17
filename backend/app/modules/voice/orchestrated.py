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
from app.agents.model import PanelModel
from app.agents.panel import interrogate, select_speaker
from app.agents.routing import choose
from app.core.logging import get_logger
from app.modules.voice.events import (
    AgentAudio,
    AgentTranscript,
    ChannelReady,
    Heartbeat,
    Interrupted,
    Spent,
    UserSpoke,
    VoiceEvent,
)
from app.modules.voice.speech import Speaker
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
        grounding: Grounding | None = None,
        reader: ClaimReader | None = None,
        transcript: TranscriptStore | None = None,
    ) -> None:
        #: Who is seated, in seat order. Public because a room's roster is a
        #: fact about the room rather than an implementation detail of it — the
        #: factory that assembles one is judged on exactly this, and captions
        #: will eventually need to name whoever is speaking.
        self.panel = panel
        self._transcriber = transcriber
        self._model = model
        self._speaker = speaker
        self._grounding = grounding
        # The reader is process-wide and stateless; the `Auditor` built around
        # it is neither, so it is made per stream in `open()` rather than here.
        self._reader = reader
        # Per room, like the panel and the grounding, and for the same reason:
        # it is bound to one session. Unlike the `Auditor` it is *not* rebuilt
        # per stream — it holds the room's ordinal counter, and a fresh one would
        # restart at zero and collide with the lines already written.
        self._transcript = transcript

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
                grounding=self._grounding,
                # A fresh one per stream, never shared. An `Auditor` accumulates
                # every figure spoken in a session, so a reused one would open
                # the next room already holding the last user's numbers — and
                # would then accuse somebody of contradicting a claim they never
                # made, quoting it verbatim in a panelist's voice. A correctness
                # failure and a privacy one in the same object.
                auditor=Auditor(reader=self._reader) if self._reader else None,
                transcript=self._transcript,
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
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
    ) -> None:
        self._panel = panel
        # Optional, like the speaker and the auditor: a room still runs without
        # somewhere to file its words, and every test that is not about
        # persistence should not have to supply one. Production always does —
        # without it the debrief has nothing to be grounded in.
        self._transcript_store = transcript
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

    async def _keep(self, line: Said) -> None:
        """File one line where it will outlive the room, if anywhere.

        Paired with every `self._transcript.append`, because the room's own
        memory and the record it leaves behind must hold the same thing — a line
        the panel is shown but that never reaches the debrief is a contradiction
        the coach cannot see and cannot be told about.
        """
        if self._transcript_store is None:
            return
        await self._transcript_store.record(line)

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
        listener = asyncio.create_task(self._listen(out))
        beating = asyncio.create_task(self._beat(out))
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
            await asyncio.gather(listener, beating, return_exceptions=True)

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

    async def _listen(self, out: asyncio.Queue[VoiceEvent | None]) -> None:
        """Read transcription forever; start, and stop, turns as it goes."""
        speaking: asyncio.Task | None = None
        try:
            async for result in self._transcription.results():
                if result.final:
                    # Before the turn is even started. This is what the relay
                    # turns into `record_speech`, and it is the only thing that
                    # resets the idle clock — panel speech deliberately does not.
                    # Emitting it after composition would leave that clock
                    # running across the slowest part of the turn, so a user who
                    # thought for eighty seconds and then answered would be
                    # reaped while the panel was replying to them.
                    await out.put(UserSpoke())
                    # Recorded here rather than inside the turn, because the turn
                    # can be cancelled and this must not be. A user who keeps
                    # talking through the panel's answer has still said the thing
                    # they said; losing it would erase their words from the room's
                    # memory because *we* chose not to reply to them, and the next
                    # selection would then judge an answer it never saw.
                    said = Said(speaker=USER, text=result.text)
                    self._transcript.append(said)
                    await self._keep(said)
                    # Collected before the new one starts, so this turn is
                    # answered with the catch from the *previous* utterance and
                    # never waits for its own. See `_audit`.
                    finding = await self._take_finding()
                    self._audit(result.text)
                    speaking = await self._restart(
                        speaking,
                        result.text,
                        out,
                        await self._take_routing(result.text),
                        finding,
                    )
                    continue

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
                if speaking is not None and not speaking.done():
                    speaking = await self._stop(speaking)
                    # Synthesis runs ahead of playback, so frames the panelist
                    # will never reach are already buffered on the phone.
                    # Stopping only what we have not sent yet lets them talk over
                    # the person who just cut in.
                    await out.put(Interrupted())

            # The stream closed. A turn still in flight is the room's last word,
            # and dropping it would lose a line the user was owed.
            if speaking is not None:
                await asyncio.gather(speaking, return_exceptions=True)
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
        """How far into the room this utterance was, from audio forwarded.

        The bytes rather than a wall clock, because they are what the room
        actually heard: a phone that reconnects, or a stream that stalls, is
        wall-clock time nobody spoke into. It is also the same counter metering
        already trusts, so a timestamp a panelist reads aloud and a second the
        user was charged for cannot disagree.
        """
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
                    ),
                ),
                "fallback",
            )
        return routing.result()

    async def _restart(
        self,
        speaking: asyncio.Task | None,
        said: str,
        out: asyncio.Queue[VoiceEvent | None],
        routed: Routed | None,
        finding: Finding | None,
    ) -> asyncio.Task:
        """Begin a turn, abandoning one already running.

        A final arriving while a panelist speaks means the user talked over them
        and finished a sentence. The `Interrupted` for that was already sent on
        the partial that opened it, so this only has to stop the work.
        """
        if speaking is not None and not speaking.done():
            await self._stop(speaking)
        return asyncio.create_task(self._turn(said, out, routed, finding))

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
            await self._answer(said, out, routed, finding)
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
    ) -> None:
        started = time.monotonic()
        turn = await interrogate(
            self._panel,
            said=said,
            model=self._model,
            grounding=Grounding(
                claims=self._claims, transcript=tuple(self._transcript)
            ),
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
        await self._keep(asked)

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
        await out.put(AgentTranscript(turn.line))

        # Reported before synthesis rather than after it, and that ordering is
        # the whole reason this is not a `finally`. A panelist cut off two words
        # in was still composed in full and still handed to the synthesiser in
        # full — both providers have already charged — so a turn that reports
        # only what the user heard would undercount precisely the interrupted
        # rooms, which is the barge-in the product is built around.
        await out.put(
            Spent(
                stt_seconds=self._seconds_heard(),
                llm_input_tokens=turn.usage.input_tokens,
                llm_output_tokens=turn.usage.output_tokens,
                tts_characters=len(turn.line) if self._speaker else 0,
            )
        )

        if self._speaker is None:
            return

        async for pcm in self._speaker.speak(
            text=turn.line, voice=turn.archetype.voice
        ):
            await out.put(AgentAudio(pcm))
