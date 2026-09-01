"""Turning a mixed room into something a phone can stream.

The half of the audio path with no judgement in it: the mixer decided *what*
the recording contains and this decides only how it is packed.
`docs/session-retention.md` puts encoding first among the three cost controls
and calls it "not a policy question" — measured at ~10x, against a vendor choice
worth ~2x.
"""

from __future__ import annotations

import array
import io
import math

import av

from app.modules.voice.mixing import SAMPLE_RATE
from app.modules.voice.encoding import M4A_CONTENT_TYPE, to_m4a


def speech_shaped(seconds: int) -> bytes:
    """Not silence. A constant-zero room compresses to nothing and would let a
    broken encoder look excellent."""
    return array.array(
        "h", (int(8000 * math.sin(i / 30.0)) for i in range(SAMPLE_RATE * seconds))
    ).tobytes()


def test_a_room_becomes_an_m4a_file_a_fraction_of_its_size():
    """The tracer bullet: PCM in, a playable object out.

    MP4/AAC rather than Ogg/Opus, decided 2026-09-01: iPhones cannot play Ogg
    at all, and MP4 is the one container both platforms' built-in players
    stream natively over HTTP ranges. Both halves asserted, because either
    alone is satisfiable by something useless: a valid container holding
    nothing compresses beautifully, and a fraction of the bytes is easy if
    they are not a file anybody can open.
    """
    raw = speech_shaped(10)

    encoded = to_m4a(raw)

    # An MP4 opens with a box length then "ftyp".
    assert encoded[4:8] == b"ftyp"
    assert len(encoded) < len(raw) / 5
    assert M4A_CONTENT_TYPE == "audio/mp4"


def test_the_index_precedes_the_audio_so_a_phone_can_start_before_the_end():
    """faststart, asserted structurally.

    AVPlayer and Media3 both begin playback from a ranged GET only if the moov
    box (the index) arrives before the mdat box (the samples). The default MP4
    mux writes moov last, which forces a full download before the first
    second plays, and nothing else in the suite would notice.
    """
    encoded = to_m4a(speech_shaped(3))

    assert encoded.index(b"moov") < encoded.index(b"mdat")


def decoded_seconds(encoded: bytes) -> float:
    """How long the object actually plays for."""
    samples = 0
    with av.open(io.BytesIO(encoded)) as container:
        rate = container.streams.audio[0].rate
        for frame in container.decode(audio=0):
            samples += frame.samples
    return samples / rate


def test_a_room_is_encoded_to_its_full_length():
    """The object plays for exactly as long as the room lasted.

    The first version of this test asserted `>= 2.9` and was worthless: it
    passed with the encoder's final flush deleted. Measuring what that flush
    actually recovers gave **6.5 ms**, constant whether the room is three
    seconds or ten minutes — one encoder buffer, not a proportion of the
    recording. So the loose threshold was hiding the very thing the test was
    named after.

    Never short, therefore, and that bound is exact. This is not protecting
    audibility — nobody hears 6.5 ms — it is protecting the claim that the
    recording is the room. A file reliably a fraction short is one somebody has
    to explain later.

    The upper bound is the codec's, not ours: AAC encodes whole 1024-sample
    frames and adds a priming buffer, so a raw decode reads up to ~0.1 s of
    padding past the room (measured: 72 ms on a 3 s room). Players that honour
    the gapless metadata trim it; the mixer seed treats it as the millisecond
    noise `from_m4a` documents.

    Asserted by decoding rather than by byte size, because a truncated file is
    still a plausible-looking file.
    """
    encoded = to_m4a(speech_shaped(3))

    played = decoded_seconds(encoded)
    assert played >= 3.0
    assert played < 3.1
