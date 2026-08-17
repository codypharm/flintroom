"""Putting a finished room where it can be played again.

The last step of the audio path, and the only one that talks to anything
outside the process. `mixing.py` decides what the recording contains,
`encoding.py` decides how it is packed, and this decides where it goes and
whether it goes at all.

Kept out of the relay because the relay is a router: `CLAUDE.md` puts business
logic in services, and "which rooms are worth keeping" is a product rule, not
plumbing.
"""

from __future__ import annotations

import asyncio
import uuid

from av.error import FFmpegError
from botocore.exceptions import ClientError

from app.core.logging import get_logger
from app.core.storage import ObjectStorage
from app.modules.voice.encoding import OPUS_CONTENT_TYPE, to_opus

log = get_logger(__name__, tag="voice")


def recording_key(session_id: uuid.UUID) -> str:
    """Where one room's audio lives.

    Keyed by session and nothing else. Not by user, and not by date: the
    retention sweep in #50 reads a room's owner and window from the database
    rather than from a key, so encoding either here would be a second copy of a
    fact that changes — a user's tier moves, and a key cannot.
    """
    return f"rooms/{session_id}.ogg"


class RoomRecordings:
    """Saves what a room sounded like, for the rooms that get one."""

    def __init__(self, storage: ObjectStorage) -> None:
        self._storage = storage

    async def save(self, *, session_id: uuid.UUID, pcm: bytes) -> None:
        """Encode one room and put it away.

        Encoding runs in a worker thread because it is twelve seconds of CPU for
        a full room — measured, see `encoding.py` — and this is called while a
        socket is closing and other rooms are live in the same process.

        Uses `ObjectStorage.put` rather than a presigned upload, which is the
        distinction `core/storage.py` draws: presigning is for bytes a *client*
        supplies, and there is no client in this loop. A room's recording is
        something the server produced, like the thumbnail extraction writes.

        Never logs the audio, and never logs a length that could stand in for
        one — how long somebody spoke is not transcript text, but it is not
        nothing either, and there is no question it answers that a duration
        column would not answer better.
        """
        if not pcm:
            # A room where nobody said anything and nothing was played. Writing
            # a valid, empty Ogg object would cost storage forever to represent
            # silence, and would make "has a recording" stop meaning "there is
            # something to hear".
            log.info("room_recording_empty", session_id=str(session_id))
            return

        try:
            encoded = await asyncio.to_thread(to_opus, pcm)
            await self._storage.put(
                recording_key(session_id), encoded, content_type=OPUS_CONTENT_TYPE
            )
        except (FFmpegError, ClientError):
            # Caught narrowly and by name, never as a bare `Exception`
            # (`CLAUDE.md`): a codec that cannot encode and a store that will not
            # take the bytes are the two things that genuinely go wrong here, and
            # anything else is a bug that must stay a traceback rather than
            # becoming a quietly missing file.
            #
            # Absorbed rather than raised, because by the time this runs the room
            # is billed, settled and handed to the debrief. Failing it now would
            # trade a lost recording for a refunded rehearsal that happened.
            log.exception("room_recording_failed", session_id=str(session_id))
            return

        log.info(
            "room_recorded", session_id=str(session_id), stored_bytes=len(encoded)
        )
