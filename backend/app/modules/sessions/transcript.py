"""One room's record, bound to the room it belongs to.

The `TranscriptStore` implementation `app/modules/voice/transcript.py` describes
— and the reason that seam is a `Protocol`: `OrchestratedChannel` is the only
object holding both sides of a room, and it has no business holding an
`AsyncSession`.

Lives in `sessions` rather than beside the seam because a transcript is what a
session *was*. `voice` is how it was produced, and the debrief that reads it is
not a voice concern at all.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import Said
from app.modules.sessions.models import TranscriptLine


class SessionTranscript:
    """What was said in one room, in the order it was said.

    **The session is bound at construction**, never passed per call — the rule
    `CLAUDE.md` sets for `LedgerService`'s actor, for the same reason: a caller
    that can name the room per line can file half a conversation under somebody
    else's session, and a transcript is exactly the artefact where that is both
    invisible and unrecoverable.
    """

    def __init__(self, db: AsyncSession, *, session_id: uuid.UUID) -> None:
        self._db = db
        self._session_id = session_id
        #: Where the next line falls. Held here because this object's lifetime
        #: *is* the room's, so the counter cannot outlive what it counts.
        #:
        #: Not a `SELECT max(ordinal) + 1` per write: that is a read-modify-write
        #: on the hot path of a live room, and it would serialise every line
        #: against every other. Not a database sequence either — a sequence is
        #: global to the table, so ordinals would be unique but not consecutive,
        #: and "the fourth thing said" would stop meaning anything.
        self._next = 0

    async def record(self, line: Said) -> None:
        """Keep one line, whoever said it.

        Flushed rather than committed. The caller owns the transaction — the
        relay already writes progress marks and spend against the same session —
        and a store that committed on its own would split those into separate
        transactions and decide, on its own authority, that a half-written turn
        was durable.

        Deliberately not logged, not even at debug. `CLAUDE.md` forbids
        transcript text in logs, and unlike a secret it cannot be caught by
        key-name redaction: it is indistinguishable from any other string.
        """
        self._db.add(
            TranscriptLine(
                session_id=self._session_id,
                ordinal=self._next,
                speaker=line.speaker,
                text=line.text,
            )
        )
        self._next += 1
        await self._db.flush()

    async def lines(self) -> tuple[Said, ...]:
        """The room, in order, both sides.

        Ordered by `ordinal` and never by `said_at`. Lines are written as they
        are said, so two can share a clock reading — and a transcript that
        occasionally transposes a question and its answer is worse than one that
        never loads, because nothing about it looks wrong.

        Returns `Said`, the same type the room reasons in, so a debrief grounded
        in a finished session and a turn grounded in a live one are looking at
        the same shape. The database row is not part of the contract.
        """
        rows = await self._db.execute(
            select(TranscriptLine)
            .where(TranscriptLine.session_id == self._session_id)
            .order_by(TranscriptLine.ordinal)
        )
        return tuple(
            Said(speaker=row.speaker, text=row.text) for row in rows.scalars()
        )
