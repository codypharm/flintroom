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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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

    #: A factory, not a session — and this is the one decision here that is not
    #: taste.
    #:
    #: `OrchestratedChannel.events` runs its listener as a task *beside* the loop
    #: the relay consumes from, and says so: "the concurrency is the feature."
    #: The relay already writes progress marks and spend from that loop. So a
    #: store sharing the room's `AsyncSession` would have two tasks flushing the
    #: same session concurrently, which SQLAlchemy does not allow — and the
    #: channel doing no database work at all is the only reason this has not
    #: happened already.
    #:
    #: It also fixes a second thing the shared session was quietly doing. A
    #: session holds a pooled connection for as long as its transaction is open,
    #: so a room that flushed without committing would pin one for twelve
    #: minutes. The engine is built on SQLAlchemy's defaults — five connections
    #: plus ten overflow — which would have capped the whole service at about
    #: fifteen concurrent rooms, from a table nobody would think to look at.
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        session_id: uuid.UUID,
        starting_at: int = 0,
    ) -> None:
        self._session_factory = session_factory
        self._session_id = session_id
        #: Where the next line falls. Held here because this object's lifetime
        #: *is* the room's, so the counter cannot outlive what it counts.
        #:
        #: Not a `SELECT max(ordinal) + 1` per write: that is a read-modify-write
        #: on the hot path of a live room, and it would serialise every line
        #: against every other. Not a database sequence either — a sequence is
        #: global to the table, so ordinals would be unique but not consecutive,
        #: and "the fourth thing said" would stop meaning anything.
        #: Non-zero for a resumed room (docs/reconnect.md), whose store must
        #: continue after the lines a previous connection already wrote —
        #: `(session_id, ordinal)` is the primary key, and a counter restarted
        #: at zero would collide with the room's own first line.
        self._next = starting_at

    async def record(self, line: Said, *, at: float | None = None) -> None:
        """Keep one line, and where the room had reached. One transaction each.

        Committed here rather than left to whoever owns the room's transaction,
        because otherwise nothing owns it: the relay commits a progress mark
        every fifteen seconds, and a line spoken at second one would become
        durable on the back of an unrelated heartbeat at second ten. That is not
        a transaction boundary, it is a coincidence — and it would change
        silently the day the heartbeat did.

        A line is its own unit of work. There is nothing it needs to be atomic
        with: it is not money, it does not move a balance, and a room where the
        third line survived and the fourth did not is still a better transcript
        than no transcript.

        The ordinal advances only after the commit lands, so a failed write is
        retried into the same slot — which the composite primary key makes a
        no-op rather than a duplicate.

        Deliberately not logged, not even at debug. `CLAUDE.md` forbids
        transcript text in logs, and unlike a secret it cannot be caught by
        key-name redaction: it is indistinguishable from any other string.
        """
        async with self._session_factory() as db:
            db.add(
                TranscriptLine(
                    session_id=self._session_id,
                    ordinal=self._next,
                    speaker=line.speaker,
                    text=line.text,
                    disputed=line.disputed,
                    rephrasing=line.rephrasing,
                    chosen_by=line.chosen_by,
                    # #69. Null rather than zero when nothing was keeping time —
                    # a room with no relay behind it, or one that ran before the
                    # clock existed. Zero would claim the top of the room.
                    began_at_seconds=at,
                )
            )
            await db.commit()
        self._next += 1

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
        async with self._session_factory() as db:
            rows = await db.execute(
                select(TranscriptLine)
                .where(TranscriptLine.session_id == self._session_id)
                .order_by(TranscriptLine.ordinal)
            )
            return tuple(
                Said(
                    speaker=row.speaker,
                    text=row.text,
                    disputed=row.disputed,
                    rephrasing=row.rephrasing,
                    chosen_by=row.chosen_by,
                )
                for row in rows.scalars()
            )
