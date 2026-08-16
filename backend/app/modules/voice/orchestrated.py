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

from collections.abc import AsyncIterator, Sequence

from app.agents.archetypes import Archetype
from app.agents.context import Grounding, Said, USER
from app.agents.model import PanelModel
from app.agents.panel import interrogate
from app.core.logging import get_logger
from app.modules.voice.events import AgentTranscript, UserSpoke, VoiceEvent
from app.modules.voice.transcription import TranscriptionStream

log = get_logger(__name__, tag="voice")


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
        grounding: Grounding | None = None,
    ) -> None:
        self._panel = panel
        self._transcription = transcription
        self._model = model
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
        """One panel turn per finished utterance.

        Partials are read and not answered. They exist so the selection hop can
        run while the user is still speaking — the entire plan for holding the
        ~1.5s threshold, since that hop measured ~0.8s — but composing on one
        would have a panelist challenge the first four words of a sentence still
        being spoken. That is not barge-in; it is not listening.
        """
        async for result in self._transcription.results():
            if not result.final:
                continue

            # Before the model call, not after. This is what the relay turns into
            # `record_speech`, and it is the only thing that resets the idle
            # clock — panel speech deliberately does not. Emitting it after
            # composition would leave the clock running across the slowest part
            # of the turn, so a user who thought for eighty seconds and then
            # answered would be reaped *while the panel was replying to them*.
            yield UserSpoke()

            turn = await interrogate(
                self._panel,
                said=result.text,
                model=self._model,
                grounding=Grounding(
                    claims=self._claims, transcript=tuple(self._transcript)
                ),
            )

            # Both sides, in order. A transcript of only the panel's questions
            # cannot tell the next selection whether anything was answered, and
            # pressing an evaded question is the most useful thing a room does.
            self._transcript.append(Said(speaker=USER, text=result.text))
            self._transcript.append(
                Said(speaker=turn.archetype.name, text=turn.line)
            )

            yield AgentTranscript(turn.line)
