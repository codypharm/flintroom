"""The seam one-shot speech-to-text plugs into.

> **Naming, and this is the third file in a neighbourhood that already had two
> confusable ones.** *Transcription* (`transcription.py`) is the live stream —
> alive only while a socket is. *Transcript* (`transcript.py`) is the record of
> what was said, and outlives the room. **Dictation is neither**: one clip in,
> one string out, no socket and no history. If a fourth arrives, read the whole
> word before assuming which one it is.

**Why the streaming seam cannot serve this.** `TranscriptionStream`'s docstring
makes interim results non-negotiable, and it is right to: the room's entire
latency plan is running selection against a partial while the user is still
speaking, so a transcriber that only speaks at the end puts the panel over
budget by construction. The debrief has none of that. It is turn-based by
decision (`docs/debrief-and-sparring.md` decision 5), runs after the room has
closed, and against no clock at all — so it wants the simplest possible shape,
and reusing a streaming seam would mean opening a socket per spoken turn, which
is precisely what that decision rejected.

Deliberately not a second method on `TranscriptionStream`. An adapter that had
to implement both would carry a streaming protocol for a caller that never
streams, and every fake in the suite would grow a method it does not use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Heard:
    """One spoken turn, as words and as what it cost to hear them.

    `seconds` travels with the text for the reason `TurnUsage` travels with a
    model reply: only the adapter knows what the provider billed for, and this
    is the unmetered phase §4.3 names as the model's largest uncontrolled
    exposure. A seam returning only text would leave the debrief's speech-to-text
    invisible to the one table that reconciles against an invoice.

    Zero rather than `None` when a provider does not report it, so a caller
    adding it up never has to special-case a vendor's silence — at the cost that
    a vendor which forgets to report looks free, which is why the adapter reads
    it explicitly rather than letting the default stand.
    """

    text: str
    seconds: float = 0.0


#: Checkable at runtime, like every other seam here: there is no type checker in
#: the suite, so an adapter that drifted off this would stay green everywhere and
#: fail only when somebody spoke to the coach.
@runtime_checkable
class Dictation(Protocol):
    """Hears one recorded turn. One instance per process."""

    async def hear(self, clip: bytes, *, media_type: str) -> Heard:
        """Turn one recorded clip into what was said.

        Bytes rather than a path or a URL: the clip arrives on a request and is
        gone afterwards. `docs/session-retention.md` keeps the interrogation's
        audio on a per-tier window and says nothing about the debrief, because
        nothing was going to store it — a coaching turn is heard, answered, and
        dropped, and the words survive only if the coach quotes them.

        `media_type` because a phone sends what it records rather than what the
        relay carries. The room's PCM16 constant is a property of the socket, and
        this is a file upload — an adapter that assumed one format would work in
        development and fail on whichever platform records the other.

        **May raise, and the caller must survive it.** Nothing is live here, so a
        failure costs a retry rather than silence in a room. It must arrive as
        `ProviderUnavailable` and must not name the vendor.
        """
        ...
