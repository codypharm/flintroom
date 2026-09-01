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
import os
import tempfile

import av

from app.modules.voice.mixing import SAMPLE_RATE

#: What the object is served as. MP4 rather than Ogg, decided 2026-09-01 with
#: the architect: iPhones cannot play Ogg at all — AVPlayer knows Opus only
#: inside CAF/MP4-family containers — while both platforms' built-in players
#: stream MP4 over HTTP ranges natively. Cross-platform is a property of the
#: file, not of React Native.
M4A_CONTENT_TYPE = "audio/mp4"

#: Bits per second. AAC-LC needs more than Opus for the same speech; 48k on
#: 16 kHz mono is transparent on a phone speaker, which is the only place
#: these are ever heard. Storage projections in `docs/session-retention.md`
#: move with this figure: a twelve-minute room lands near 4.3 MB instead of
#: Opus's 2.9 MB, still an order of magnitude under the PCM it replaces.
BIT_RATE = 48_000

#: How much is handed to the encoder at a time. Large enough that per-call
#: overhead disappears, small enough that a room is never copied whole into a
#: second buffer beside the one it already occupies.
_CHUNK_SAMPLES = SAMPLE_RATE


def to_m4a(pcm: bytes) -> bytes:
    """One room's mixed PCM16, as an MP4/AAC object.

    **Blocking, and meant to be.** Twelve seconds of CPU for a full room is far
    too long for the event loop, so every caller runs this through
    `asyncio.to_thread`. Making it a coroutine would hide that: it would look
    awaitable and still hold the loop for the whole encode.

    Mono at 16 kHz throughout, matching the relay's format in both directions —
    AAC-LC supports that rate natively, so nothing here resamples and no
    quality is spent converting between formats that were already agreed.

    `faststart` moves the index (moov) ahead of the samples, which is what
    lets a phone begin playing from a ranged GET instead of downloading the
    whole room first. The muxer does that with a rewrite pass on close, and
    the rewrite needs a real, named file: over an in-memory stream ffmpeg
    tries to open a sibling temp file called "<none>" and dies. So this
    encodes to a temp file and reads it back — one extra copy of a few
    megabytes, on a call that is already twelve seconds of CPU.
    """
    handle = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
    handle.close()
    try:
        _encode_into(handle.name, pcm)
        with open(handle.name, "rb") as done:
            return done.read()
    finally:
        os.unlink(handle.name)


def _encode_into(path: str, pcm: bytes) -> None:
    with av.open(
        path, mode="w", format="mp4", options={"movflags": "+faststart"}
    ) as container:
        stream = container.add_stream("aac", rate=SAMPLE_RATE)
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

def from_m4a(encoded: bytes) -> bytes:
    """A stored MP4/AAC room, back as the PCM16 it was mixed from.

    The other half of `to_m4a`, and it exists for one caller: seeding a
    resumed room's mixer with the segment the dropped connection stored
    (docs/reconnect.md), so the clock — and with it every transcript offset —
    continues instead of restarting. Blocking for the same reason `to_m4a`
    is, and run through `asyncio.to_thread` by that caller.

    Lossy about the waveform and not about time: the codec decodes to the
    length it encoded, give or take its own priming — milliseconds, which is
    noise against offsets read by humans scrubbing a player.
    """
    pcm = io.BytesIO()

    # `mode="r"` is what the stubs need to know this is an input container —
    # the same call the tests make without it, and the read is the default.
    with av.open(io.BytesIO(encoded), mode="r") as container:
        # Back to the wire's own format whatever the file says — kept from
        # the Opus era, where the decoder came back at 48 kHz regardless of
        # what it was fed. AAC decodes at its stored rate, so this is now a
        # no-op that costs nothing and keeps the seed correct if the codec
        # ever changes again.
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(audio=0):
            for resampled in resampler.resample(frame):
                pcm.write(bytes(resampled.planes[0])[: resampled.samples * 2])
        for resampled in resampler.resample(None):
            pcm.write(bytes(resampled.planes[0])[: resampled.samples * 2])

    return pcm.getvalue()
