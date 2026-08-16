"""A room we run ourselves.

`ElevenLabsProvider` hands a whole conversation to one remote agent, and that
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
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from app.agents.archetypes import Archetype
from app.agents.context import Grounding, Said, USER
from app.agents.model import PanelModel
from app.agents.panel import interrogate
from app.core.logging import get_logger
from app.modules.voice.events import (
    AgentAudio,
    AgentTranscript,
    ChannelReady,
    Interrupted,
    UserSpoke,
    VoiceEvent,
)
from app.modules.voice.speech import Speaker
from app.modules.voice.transcription import Transcriber, TranscriptionStream

log = get_logger(__name__, tag="voice")


class OrchestratedProvider:
    """Opens rooms we run ourselves. **One instance per room, not per process.**

    That is the one way this differs from `ElevenLabsProvider`, and it follows
    from an asymmetry rather than from taste. ElevenLabs needs no arguments to
    `open()` because which agent, what persona and what voice all live on their
    dashboard; they already know. Ours has to be told which archetypes are seated
    and which deck to attack, and both are per-session facts in our database.

    Resolved at construction rather than by widening `VoiceProvider.open()`. The
    shared seam stays untouched, `ElevenLabsProvider` never grows a parameter it
    could not use, and the relay keeps knowing nothing about decks. It is also
    the call `CLAUDE.md` already makes for audit actors — context bound when the
    service is built, never passed per call — for the same reason: a caller that
    could name the room per call could name a different one halfway through.

    The vendors it composes are still undecided. `transcriber` is the last
    unchosen link in the chain, and `speaker` is optional because a silent panel
    is a legitimate development configuration while an untestable one is not.
    """

    def __init__(
        self,
        *,
        panel: Sequence[Archetype],
        transcriber: Transcriber,
        model: PanelModel,
        speaker: Speaker | None = None,
        grounding: Grounding | None = None,
    ) -> None:
        self._panel = panel
        self._transcriber = transcriber
        self._model = model
        self._speaker = speaker
        self._grounding = grounding

    @asynccontextmanager
    async def open(self) -> AsyncIterator[OrchestratedChannel]:
        """Dial the transcriber and build a room around it.

        The stream closes on every path out, including the failing ones — which
        are the only ones that ever leak. An open transcription stream is a room
        still running on somebody's invoice with nobody in it.
        """
        async with self._transcriber.open() as transcription:
            yield OrchestratedChannel(
                panel=self._panel,
                transcription=transcription,
                model=self._model,
                speaker=self._speaker,
                grounding=self._grounding,
            )


class OrchestratedChannel:
    """One interrogation, driven turn by turn.

    Holds the transcript for the life of the room and nothing beyond it. What a
    saved session retains is an open product decision, so this deliberately
    accumulates in memory and writes none of it — adding persistence here would
    answer that question by accident, and in the direction that keeps the most
    data.
    """

    def __init__(
        self,
        *,
        panel: Sequence[Archetype],
        transcription: TranscriptionStream,
        model: PanelModel,
        speaker: Speaker | None = None,
        grounding: Grounding | None = None,
    ) -> None:
        self._panel = panel
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

    async def send_audio(self, pcm: bytes) -> None:
        """Straight through to the transcriber.

        No buffering and no voice-activity decision here. Endpointing is a thing
        transcribers are good at and this module would be bad at, and doing it in
        two places is how the two disagree about when the user stopped.
        """
        await self._transcription.send_audio(pcm)

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

        out: asyncio.Queue[VoiceEvent | None] = asyncio.Queue()
        listener = asyncio.create_task(self._listen(out))
        try:
            while (event := await out.get()) is not None:
                yield event
        finally:
            # The consumer may stop early — the relay cancels this side whenever
            # the phone hangs up first. Without this the listener survives its
            # own room, holding a transcription stream open on somebody's
            # invoice with nobody reading it.
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)

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
                    self._transcript.append(Said(speaker=USER, text=result.text))
                    speaking = await self._restart(speaking, result.text, out)
                    continue

                # A partial, which is the user starting to talk. If somebody is
                # mid-sentence they lose the floor now rather than at the end of
                # their line — waiting for the *final* would mean waiting for the
                # user to finish speaking before conceding, which is a panelist
                # talking over them for three seconds and then stopping politely.
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
            await out.put(None)

    async def _restart(
        self,
        speaking: asyncio.Task | None,
        said: str,
        out: asyncio.Queue[VoiceEvent | None],
    ) -> asyncio.Task:
        """Begin a turn, abandoning one already running.

        A final arriving while a panelist speaks means the user talked over them
        and finished a sentence. The `Interrupted` for that was already sent on
        the partial that opened it, so this only has to stop the work.
        """
        if speaking is not None and not speaking.done():
            await self._stop(speaking)
        return asyncio.create_task(self._turn(said, out))

    @staticmethod
    async def _stop(speaking: asyncio.Task) -> None:
        speaking.cancel()
        # Awaited rather than abandoned, for the reason the relay gives: a
        # cancelled task nobody collects is reported at interpreter exit, long
        # after the context that would have explained it is gone.
        await asyncio.gather(speaking, return_exceptions=True)
        return None

    async def _turn(self, said: str, out: asyncio.Queue[VoiceEvent | None]) -> None:
        """One archetype's answer, from selection through to the last frame."""
        turn = await interrogate(
            self._panel,
            said=said,
            model=self._model,
            grounding=Grounding(
                claims=self._claims, transcript=tuple(self._transcript)
            ),
        )

        # Recorded before the line is spoken, so that a panelist cut off two
        # words in is still on record as having asked. The next selection has to
        # know the question was put — otherwise a user who talks over the CFO
        # hears the same challenge again, which reads as a room that is not
        # listening rather than one that was interrupted.
        #
        # The user's own line was recorded by the listener, not here, because
        # this task can be cancelled and that must not depend on it.
        self._transcript.append(Said(speaker=turn.archetype.name, text=turn.line))

        # The caption first, then the audio it captions. Synthesis streams over
        # the length of an utterance, so a client waiting for the last frame
        # before displaying the line would caption the room seconds late — and
        # captions are in the v1 accessibility floor, not a garnish on the audio.
        await out.put(AgentTranscript(turn.line))

        if self._speaker is None:
            return

        async for pcm in self._speaker.speak(
            text=turn.line, voice_id=turn.archetype.voice_id
        ):
            await out.put(AgentAudio(pcm))
