"""How far into the room we are — the seam a transcript line is stamped from.

A `Protocol` for the reason `TranscriptStore` beside it is one. The clock is
`RoomMixer`, which lives on the relay because the relay is the only place the
user's audio, the panel's audio and `Interrupted` all meet; the thing that needs
to *read* it is `OrchestratedChannel`, which drives agents and has no business
knowing what a sample is. Between them there has to be a seam or a dependency,
and every other collaborator that module takes is a seam.

**Why a mixer is a clock at all.** The user's uplink is continuous and ungated —
`app/src/lib/audio/uplink.ts` sends every frame the recorder produces with no
voice-activity decision — so the mixer's count of user samples advances at one
second per second of room. It is therefore not merely *a* clock but the only one
whose readings are positions in the file a player seeks into, which is what #69
is for.

The alternative was a monotonic wall clock started at `ChannelReady`. It was
rejected because it drifts from the recording exactly when the uplink stalls,
and a stalled uplink is the case where it would look correct and be wrong.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


#: Checkable at runtime for the reason `TranscriptStore` and `TranscriptionStream`
#: are: there is no base class to inherit, so a renamed method here would stay
#: green everywhere and fail only in a live room.
@runtime_checkable
class RoomClock(Protocol):
    """Where the room has got to, in seconds from its first frame."""

    def elapsed(self) -> float:
        """Seconds of room so far.

        Zero from a room that has heard nothing, which is a true statement about
        a room nobody has spoken into rather than a missing reading — a room
        with no clock at all is `None` at the call site, and the two must not be
        confused.

        Synchronous, because it reads a counter. An `async` clock would be one
        more `await` on the hot path of a live room for a division.
        """
        ...
