"""The seam speech-to-text plugs into.

The last undecided vendor in the chain, and the reason it is a `Protocol` before
it is a choice: every other vendor in this stack sits behind one — `ObjectStorage`,
`VoiceChannel`, `ExtractionModel`, `PanelModel` — and picking a transcriber by
argument rather than by measurement would be the one exception. The adapter is
where the decision goes; nothing above this file learns the vendor's name.

**One requirement is not negotiable, and it is the reason `final` exists.** The
transcriber must emit interim results. The whole plan for holding the ~1.5s
illusion threshold (Open Risk #3) is running the selection hop — measured at
~0.8s — against a partial transcript while the user is still speaking, so it has
already landed when they stop. A transcriber that only speaks at the end of an
utterance makes that overlap impossible, and the room is over budget by
construction regardless of how fast the vendor itself is. Weigh candidates on
that before latency.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Transcription:
    """What the user has said so far, or what they finished saying.

    One type with a flag rather than two types, because consumers overwhelmingly
    want *the latest text* and only occasionally care whether it is settled. Two
    events would make the common case a union match.
    """

    #: The utterance as heard. For a partial, everything since the last final —
    #: not a delta. A consumer holding the newest string always holds the whole
    #: utterance, and never has to accumulate fragments correctly to be correct.
    text: str

    #: Whether the user has stopped. Only a final result is answered; a partial
    #: exists to let work start early, never to be replied to.
    final: bool


#: Checkable at runtime because nothing else in this project would catch an
#: adapter drifting off the seam. There is no base class to inherit and no type
#: checker in the suite, so a renamed method here stays green everywhere and
#: fails only when the adapter reaches a live room. `isinstance` proves the
#: methods exist and nothing about their signatures — which is exactly the class
#: of mistake that would otherwise go unnoticed until it was expensive.
@runtime_checkable
class TranscriptionStream(Protocol):
    """One live transcription, for the length of one room."""

    async def send_audio(self, pcm: bytes) -> None:
        """Forward what the user said. PCM16, 16 kHz mono.

        The same format and the same contract as `VoiceChannel.send_audio`, so
        the relay's audio path is unchanged whichever provider is in use. Any
        re-encoding a vendor demands happens inside its adapter.
        """
        ...

    def results(self) -> AsyncIterator[Transcription]:
        """Partials and finals, in order, until the stream closes.

        Ends when the connection does, not when the user goes quiet. Silence is
        an ordinary part of a hostile Q&A — somebody thinking before answering is
        still in the room — and deciding otherwise is the idle timeout's job, on
        a clock the session owns.
        """
        ...


@runtime_checkable
class Transcriber(Protocol):
    """Opens transcription streams. One instance per process."""

    def open(self) -> AbstractAsyncContextManager[TranscriptionStream]:
        """Dial the transcriber.

        A context manager for the reason `VoiceProvider.open` is one: an
        unclosed stream is a room still running on somebody's invoice, and that
        must not depend on the caller tidying up on every path out — including
        the failing ones.
        """
        ...
