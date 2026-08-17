"""The room as it sounded, on one timeline.

`docs/session-retention.md` decides that a saved session is a single mixed Opus
object. This is the part that decides *what goes in it* — encoding is a separate
step and a separate task, because this half is where the correctness risk is and
it can be tested exactly, in PCM, with no codec anywhere near it.

Nothing here awaits, and that is deliberate rather than incidental. The relay
carries user audio on one task and provider events on another
(`relay.py:105`), so these methods are called from two coroutines. Keeping them
free of `await` is what makes them atomic under asyncio: a method that cannot
yield cannot interleave with another, and no lock is needed to say so.
"""

from __future__ import annotations

import array

#: PCM16 little-endian, matching the relay in both directions.
_SAMPLE = "h"

#: What the relay carries, and therefore what a sample is worth in wall clock.
SAMPLE_RATE = 16_000

#: The longest room this will hold in memory, in seconds.
#:
#: **Deliberately not `SESSION_LIMIT`, and deliberately larger than it.** A room
#: is capped at twelve minutes today, which is the only reason a live one costs
#: ~23 MB of PCM16 — but that constant lives in `sessions/schemas.py`, is a
#: decision about how long a rehearsal should be, and could reasonably be raised
#: by somebody thinking about nothing but session length. Importing it here would
#: make this module's memory ceiling move silently when they did, at ~1.92 MB per
#: minute per concurrent room.
#:
#: Set above the session cap so it never fires in an ordinary room: this is a
#: backstop against unbounded growth, not a second session limit competing with
#: the first. If it starts firing, the two have drifted and that is the thing to
#: look at.
RECORDING_LIMIT_SECONDS = 20 * 60


class RoomMixer:
    """One room, accumulating as it happens."""

    def __init__(self, *, max_samples: int | None = None) -> None:
        self._room = array.array(_SAMPLE)
        self._max_samples = (
            max_samples
            if max_samples is not None
            else RECORDING_LIMIT_SECONDS * SAMPLE_RATE
        )
        #: Whether anything was dropped for want of room. Reported rather than
        #: raised: a room that stopped recording still interrogates, still
        #: settles and still bills correctly, and failing one over its own
        #: recording would trade a complete rehearsal for a partial file.
        self.truncated = False
        #: How far the *user's* stream has reached, in samples — and therefore
        #: what time it is. The uplink is continuous and ungated, so this
        #: advances at exactly one second of samples per second of room.
        self._heard = 0
        #: How far the *panel* has been laid down. Runs ahead of `_heard`
        #: whenever a panelist is mid-utterance, and that gap is precisely the
        #: audio that has been sent but not yet played.
        self._playing = 0

    def heard(self, pcm: bytes) -> None:
        """What the microphone picked up. Advances the room's clock.

        Always written at the user's own frontier, never appended to whatever
        the array happens to end with — a panelist speaking may already have
        written past this point, and the user's next word belongs *underneath*
        it rather than after it.
        """
        self._heard = self._mix(at=self._heard, pcm=pcm)

    def played(self, pcm: bytes) -> None:
        """What went out to the phone's speaker.

        Anchored to the clock when an utterance begins and laid consecutively
        from there, which is what puts it where it was *heard* rather than where
        it arrived. Synthesis streams faster than real time, so an eight-second
        answer can reach us inside one second — writing it at the arrival point
        would compress the panel into a fraction of the room and drag every
        later line out of place.
        """
        self._playing = self._mix(at=max(self._playing, self._heard), pcm=pcm)

    def interrupted(self) -> None:
        """The user cut in, and the phone threw away what it had not played.

        Drops everything past the clock, which is exactly the audio that was
        synthesised, sent, and never heard — the relay's counterpart to this is
        `discard_playback`, and the two have to agree or the recording disagrees
        with the room.

        No knowledge of what the phone actually rendered is needed, and that is
        the point. Playback runs at real time and the user's uplink runs at real
        time, so their frontier answers "how far had this got" without a single
        timestamp crossing the wire — where it would be a clock we do not
        control, on a device we cannot trust to be honest about it.
        """
        del self._room[self._heard :]
        self._playing = self._heard

    def mixed(self) -> bytes:
        """The room so far, as PCM16."""
        return self._room.tobytes()

    def _mix(self, *, at: int, pcm: bytes) -> int:
        """Add samples into the room at a position, and say where they end.

        Addition rather than assignment, because PCM is a pressure wave: two
        sources in one room sum, and overwriting would silence whichever was
        written second — which during barge-in is always the user.

        Clamped rather than allowed to wrap. Signed 16-bit arithmetic that
        overflows does not distort, it inverts: a loud moment becomes a loud
        moment of the opposite sign, which is heard as a click. Barge-in is
        exactly when both sources are loud at once.
        """
        samples = array.array(_SAMPLE, pcm)

        # Trimmed at the far end rather than refused outright, so a room that
        # reaches the ceiling mid-utterance keeps the part that fits.
        #
        # Both cursors then stall at the cap, because this returns where the
        # *stored* samples end. That is deliberate: past this point nothing more
        # is recorded, so there is no position left to be right about, and a
        # clock that kept running would only invite arithmetic on a region that
        # does not exist.
        if at + len(samples) > self._max_samples:
            self.truncated = True
            del samples[max(0, self._max_samples - at) :]

        if len(self._room) < at + len(samples):
            self._room.extend([0] * (at + len(samples) - len(self._room)))

        for offset, sample in enumerate(samples):
            total = self._room[at + offset] + sample
            self._room[at + offset] = max(-32768, min(32767, total))

        return at + len(samples)
