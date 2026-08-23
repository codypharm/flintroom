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

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.storage import ObjectStorage
from app.modules.sessions.models import SessionRecording
from sqlalchemy.dialects.postgresql import insert

from app.modules.voice.encoding import OPUS_CONTENT_TYPE, from_opus, to_opus

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

    def __init__(
        self, storage: ObjectStorage, *, db: AsyncSession | None = None
    ) -> None:
        self._storage = storage
        # Optional so the relay can be exercised without a database in the
        # picture. A room with no row is still playable — the key is
        # deterministic — but it is invisible to the retention sweep, which is
        # why nothing serving a real user may omit it.
        self._db = db

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

        # Written after the object, never before. A row promising audio that
        # does not exist would make the sweep chase a key forever and the
        # playback endpoint hand out a URL to nothing. The opposite order costs
        # storage until somebody notices — worse for us, invisible to the user,
        # and that is the trade being made.
        if self._db is not None:
            # An upsert, because two saves per room is the reconnect window's
            # ordinary shape (docs/reconnect.md): the dropped relay stores its
            # segment, and the resumed relay's final save replaces it with the
            # whole room. The row follows the object — same key, newer size —
            # rather than crashing on its own primary key.
            await self._db.execute(
                insert(SessionRecording)
                .values(session_id=session_id, byte_size=len(encoded))
                .on_conflict_do_update(
                    index_elements=["session_id"],
                    set_={"byte_size": len(encoded)},
                )
            )
            await self._db.commit()

        log.info(
            "room_recorded", session_id=str(session_id), stored_bytes=len(encoded)
        )

    async def saved_pcm(self, *, session_id: uuid.UUID) -> bytes:
        """What this room already sounds like, decoded — a resumed mixer's seed.

        docs/reconnect.md: the relay that lost its socket saved the segment it
        heard, and the relay that resumes must continue that recording rather
        than start a second one — the mixer's clock is what transcript offsets
        are read from, and a clock restarted at zero would anchor every
        pre-drop line into a file missing its moment.

        Empty rather than raising, on every path: a room never saved, a store
        that cannot answer, an object that will not decode. A resume must not
        fail over its own recording — the seed is best-effort for exactly the
        reason the save is.
        """
        try:
            stored = await self._storage.get(recording_key(session_id))
        except ClientError:
            log.exception("room_recording_unreadable", session_id=str(session_id))
            return b""
        if stored is None:
            return b""

        try:
            return await asyncio.to_thread(from_opus, stored)
        except FFmpegError:
            log.exception("room_recording_undecodable", session_id=str(session_id))
            return b""
