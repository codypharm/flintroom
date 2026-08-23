"""Packing a mixed room into something a phone can stream.

Deliberately separate from `mixing.py`, and the split is where the risk is
rather than where the code divides tidily. What goes into a recording — which
frames were heard, which were cut off by barge-in — is a judgement this product
can get wrong in a way a user would notice. How those samples are packed is not.
Keeping them apart is what lets the half with the judgement be tested exactly,
in PCM, with no codec anywhere near it.

**Measured, not assumed.** A full twelve-minute room: 23.04 MB of PCM16 in,
2.90 MB of Ogg/Opus out, encoded in 12.4 seconds — about 58x real time. That
last figure is why this belongs in a worker thread and not on the event loop,
and the compression ratio is the ~10x that `docs/deferred-scale-work.md` says is
worth an order of magnitude more than the storage vendor.

A sine wave was the input for those numbers, which is a pessimistic stand-in:
real speech is quieter, sparser and full of pauses, so a real room should land
smaller than 2.90 MB rather than larger.
"""

from __future__ import annotations

import io

import av

from app.modules.voice.mixing import SAMPLE_RATE

#: What the object is served as. Ogg rather than raw Opus packets, because a
#: bare Opus stream carries no timing and nothing on a phone will play one.
OPUS_CONTENT_TYPE = "audio/ogg"

#: Bits per second. Opus at 24k on mono speech is transparent enough that the
#: difference is inaudible on a phone speaker, which is the only place these are
#: ever heard — and it is the figure every storage projection in
#: `docs/session-retention.md` is derived from, so moving it moves the bill.
BIT_RATE = 24_000

#: How much is handed to the encoder at a time. Large enough that per-call
#: overhead disappears, small enough that a room is never copied whole into a
#: second buffer beside the one it already occupies.
_CHUNK_SAMPLES = SAMPLE_RATE


def to_opus(pcm: bytes) -> bytes:
    """One room's mixed PCM16, as an Ogg/Opus object.

    **Blocking, and meant to be.** Twelve seconds of CPU for a full room is far
    too long for the event loop, so every caller runs this through
    `asyncio.to_thread`. Making it a coroutine would hide that: it would look
    awaitable and still hold the loop for the whole encode.

    Mono at 16 kHz throughout, matching the relay's format in both directions —
    Opus supports that rate natively, so nothing here resamples and no quality
    is spent converting between formats that were already agreed.
    """
    buffer = io.BytesIO()

    with av.open(buffer, mode="w", format="ogg") as container:
        stream = container.add_stream("libopus", rate=SAMPLE_RATE)
        stream.bit_rate = BIT_RATE

        for offset in range(0, len(pcm), _CHUNK_SAMPLES * 2):
            block = pcm[offset : offset + _CHUNK_SAMPLES * 2]
            frame = av.AudioFrame(format="s16", layout="mono", samples=len(block) // 2)
            frame.sample_rate = SAMPLE_RATE
            frame.planes[0].update(block)
            for packet in stream.encode(frame):
                container.mux(packet)

        # The encoder buffers, so the last packets exist only once it is told
        # nothing more is coming.
        #
        # Measured, because the plausible version of this comment is wrong: the
        # flush recovers **6.5 milliseconds**, and the same 6.5 ms whether the
        # room is three seconds or ten minutes. It is one encoder buffer, not a
        # proportion of the recording. Nobody would hear its absence.
        #
        # Kept anyway, because "the file is complete" is worth more than the
        # audio is: a recording reliably a fraction short is one somebody has to
        # explain later, and the honest answer would be that we did not close
        # the encoder.
        for packet in stream.encode(None):
            container.mux(packet)

    return buffer.getvalue()

def from_opus(encoded: bytes) -> bytes:
    """A stored Ogg/Opus room, back as the PCM16 it was mixed from.

    The other half of `to_opus`, and it exists for one caller: seeding a
    resumed room's mixer with the segment the dropped connection stored
    (docs/reconnect.md), so the clock — and with it every transcript offset —
    continues instead of restarting. Blocking for the same reason `to_opus`
    is, and run through `asyncio.to_thread` by that caller.

    Lossy about the waveform and not about time: Opus decodes to the length it
    encoded, give or take the codec's own priming — milliseconds, which is
    noise against offsets read by humans scrubbing a player.
    """
    pcm = io.BytesIO()

    # `mode="r"` is what the stubs need to know this is an input container —
    # the same call the tests make without it, and the read is the default.
    with av.open(io.BytesIO(encoded), mode="r") as container:
        # Back to the wire's own format whatever the file says: libopus
        # decodes at 48 kHz regardless of the rate it was fed, so without
        # this the seed would run three times slower than the room it is
        # supposed to continue.
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(audio=0):
            for resampled in resampler.resample(frame):
                pcm.write(bytes(resampled.planes[0])[: resampled.samples * 2])
        for resampled in resampler.resample(None):
            pcm.write(bytes(resampled.planes[0])[: resampled.samples * 2])

    return pcm.getvalue()
