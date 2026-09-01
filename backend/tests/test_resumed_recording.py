"""A room's recording, across a reconnect — docs/reconnect.md.

The exiting relay saves what it heard; the resumed relay starts a fresh mixer.
Without a seed, the resumed room's final save would overwrite the pre-drop
audio with only the tail, and every transcript offset written before the drop
would anchor into a file that no longer contains that moment. So the resumed
mixer is seeded with the decoded stored segment: the clock continues, the
offsets stay honest, and the final save holds the whole room.
"""

from __future__ import annotations

import array
import math
import uuid

import pytest
from sqlalchemy import func, select

from app.modules.sessions.models import SessionRecording
from app.modules.voice.encoding import from_m4a, to_m4a
from app.modules.voice.mixing import SAMPLE_RATE, RoomMixer
from app.modules.voice.recording import RoomRecordings

pytestmark = pytest.mark.asyncio


def _tone(seconds: float) -> bytes:
    samples = array.array("h")
    for n in range(int(seconds * SAMPLE_RATE)):
        samples.append(int(12_000 * math.sin(2 * math.pi * 440 * n / SAMPLE_RATE)))
    return samples.tobytes()


#: What AAC may add, never subtract: priming plus a tail padded to whole
#: 1024-sample frames, a fixed ~0.1 s regardless of room length (measured:
#: 112 ms on 2 s, 88 ms on 1 s). Absolute rather than relative, because a
#: fixed pad reads as enormous drift on a tiny test clip and as nothing on a
#: real room — and the seed's clock cares about seconds, not percentages.
_CODEC_PAD_BYTES = int(0.15 * SAMPLE_RATE) * 2


def test_a_stored_room_decodes_back_to_the_length_it_had():
    """The codec is lossy about waveforms, not about time. The seed's whole
    job is carrying the clock, so length is the property that matters: never
    shorter than the room, and longer only by the codec's fixed pad."""
    pcm = _tone(2.0)

    decoded = from_m4a(to_m4a(pcm))

    assert len(decoded) % 2 == 0
    assert len(decoded) >= len(pcm)
    assert len(decoded) - len(pcm) < _CODEC_PAD_BYTES


def test_a_seeded_mixer_continues_the_clock_instead_of_restarting_it():
    seed = _tone(3.0)
    mixer = RoomMixer(resumed=seed)

    assert mixer.elapsed() == pytest.approx(3.0, abs=0.01)

    mixer.heard(_tone(1.0))

    assert mixer.elapsed() == pytest.approx(4.0, abs=0.01)
    # The final save is the whole room: what the first connection stored,
    # then what this one heard.
    assert mixer.mixed()[: len(seed)] == seed


def test_a_room_kept_off_seeds_nothing_and_owes_nothing():
    """No stored audio, so nothing to seed — and nothing consumes the offsets
    either, because offsets exist to anchor playback of a file that will
    never be written."""
    mixer = RoomMixer(keeping=False, resumed=_tone(1.0))

    assert mixer.elapsed() == 0.0
    assert mixer.mixed() == b""


async def test_the_stored_segment_comes_back_as_the_next_mixers_seed(
    storage, db, sessions, funded_account
):
    session_id = (await sessions.start(user_id=funded_account.user_id)).id
    recordings = RoomRecordings(storage, db=db)
    await recordings.save(session_id=session_id, pcm=_tone(1.0))

    seed = await recordings.saved_pcm(session_id=session_id)

    assert len(seed) >= len(_tone(1.0))
    assert len(seed) - len(_tone(1.0)) < _CODEC_PAD_BYTES


async def test_a_room_never_saved_seeds_empty(storage):
    seed = await RoomRecordings(storage).saved_pcm(session_id=uuid.uuid4())

    assert seed == b""


async def test_saving_twice_keeps_one_row_with_the_newer_size(
    storage, db, sessions, funded_account
):
    """Two saves per room is the reconnect window's ordinary shape: the
    dropped relay stores its segment, and the resumed relay's final save
    replaces it with the whole room. The row must follow the object rather
    than crash on its own primary key."""
    session_id = (await sessions.start(user_id=funded_account.user_id)).id
    recordings = RoomRecordings(storage, db=db)

    await recordings.save(session_id=session_id, pcm=_tone(1.0))
    await recordings.save(session_id=session_id, pcm=_tone(2.0))

    rows = await db.execute(
        select(func.count(), func.max(SessionRecording.byte_size)).where(
            SessionRecording.session_id == session_id
        )
    )
    count, size = rows.one()
    assert count == 1
    assert size == len(to_m4a(_tone(2.0)))
