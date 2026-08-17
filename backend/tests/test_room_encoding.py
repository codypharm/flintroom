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
from app.modules.voice.encoding import OPUS_CONTENT_TYPE, to_opus


def speech_shaped(seconds: int) -> bytes:
    """Not silence. A constant-zero room compresses to nothing and would let a
    broken encoder look excellent."""
    return array.array(
        "h", (int(8000 * math.sin(i / 30.0)) for i in range(SAMPLE_RATE * seconds))
    ).tobytes()


def test_a_room_becomes_an_ogg_file_a_tenth_of_its_size():
    """The tracer bullet: PCM in, a playable object out.

    Both halves asserted, because either alone is satisfiable by something
    useless — a valid container holding nothing compresses beautifully, and a
    tenth of the bytes is easy if they are not a file anybody can open.
    """
    raw = speech_shaped(10)

    encoded = to_opus(raw)

    assert encoded[:4] == b"OggS"
    assert len(encoded) < len(raw) / 5
    assert OPUS_CONTENT_TYPE == "audio/ogg"


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

    Exact length rather than a tolerance, therefore. This is not protecting
    audibility — nobody hears 6.5 ms — it is protecting the claim that the
    recording is the room. A file reliably a fraction short is one somebody has
    to explain later.

    Asserted by decoding rather than by byte size, because a truncated file is
    still a plausible-looking file.
    """
    encoded = to_opus(speech_shaped(3))

    assert decoded_seconds(encoded) == 3.0
