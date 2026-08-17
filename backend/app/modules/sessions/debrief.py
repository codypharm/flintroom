"""What the debrief knows about a room that has closed.

`docs/debrief-and-sparring.md` decision 1: the ranked weak-answer list is born
when the debrief first opens, written once, and read afterwards by the coach,
the prep sheet and #55's calibration.

**Not at settlement.** That path has four callers — the meter's cap, the
router's End, the relay, and the reaper — and it is where billing closes. The
relay already learned what hanging non-billing work there costs: a lost
recording must not become a lost settlement. A multi-second model call would
repeat the risk for something that is not billing, on every room, including the
ones nobody comes back to.

**Written once, and that is not only about cost.** The ranking is a model's
reading and moves between runs on the same transcript — measured, in
`scripts/weakness.py`. A list recomputed on every open would reshuffle under
somebody working through it, and the prep sheet they screenshotted would stop
matching the screen.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.weakness import WeakAnswer, Weakness, WeaknessReader, weak_answers
from app.core.errors import (
    RoomBroke,
    RoomHasNoQuestions,
    SessionNotFound,
    SessionNotSettled,
)
from app.core.logging import get_logger
from app.modules.sessions.models import Session, SessionWeakAnswer, TranscriptLine
from app.modules.sessions.schemas import EndReason, SessionState
from app.agents.context import USER, Said

log = get_logger(__name__, tag="debrief")


class DebriefService:
    """The ranked list, computed once per room and kept."""

    def __init__(self, db: AsyncSession, *, reader: WeaknessReader) -> None:
        self._db = db
        self._reader = reader

    async def weak_answers(
        self, *, session_id: uuid.UUID
    ) -> tuple[WeakAnswer, ...]:
        """What went badly in this room, worst first.

        Reads the stored list if there is one, and only reads the room when
        there is not. The check is the cheap query rather than a flag on the
        session: a flag and the rows are two facts that can disagree, and the
        rows are the ones anybody would trust.
        """
        if kept := await self._kept(session_id):
            return kept

        session = await self._settled(session_id)

        if session.end_reason is EndReason.PROVIDER_FAILURE:
            raise RoomBroke(session_id=str(session_id))

        transcript = await self._transcript(session_id)

        if not any(line.speaker != USER for line in transcript):
            raise RoomHasNoQuestions(session_id=str(session_id))

        ranked = await weak_answers(
            transcript, ended=session.end_reason, reader=self._reader
        )

        log.info(
            "weak_answers_read",
            session_id=str(session_id),
            found=len(ranked.answers),
            input_tokens=ranked.usage.input_tokens,
            output_tokens=ranked.usage.output_tokens,
        )

        return await self._keep(session_id, ranked.answers)

    async def _kept(self, session_id: uuid.UUID) -> tuple[WeakAnswer, ...]:
        """The stored list, in the order the model put it in."""
        rows = await self._db.execute(
            select(SessionWeakAnswer)
            .where(SessionWeakAnswer.session_id == session_id)
            .order_by(SessionWeakAnswer.rank)
        )
        return tuple(
            WeakAnswer(
                ordinal=row.ordinal,
                question=row.question,
                asked_by=row.asked_by,
                answer=row.answer,
                weakness=Weakness(row.weakness),
                why=row.why,
            )
            for row in rows.scalars()
        )

    async def _keep(
        self, session_id: uuid.UUID, answers: tuple[WeakAnswer, ...]
    ) -> tuple[WeakAnswer, ...]:
        """Write the list, or accept the one that got there first.

        Two devices opening the debrief at the same moment both read the room
        and both try to write. That is a wasted call rather than a fault, and
        the loser must hand back the winner's list rather than its own — the
        two are different readings of the same transcript, and a user whose
        second device showed a different ranking would be right to distrust
        both.
        """
        self._db.add_all(
            SessionWeakAnswer(
                session_id=session_id,
                rank=rank,
                ordinal=answer.ordinal,
                question=answer.question,
                asked_by=answer.asked_by,
                answer=answer.answer,
                weakness=answer.weakness.value,
                why=answer.why,
            )
            for rank, answer in enumerate(answers)
        )

        try:
            await self._db.commit()
        except IntegrityError:
            await self._db.rollback()
            log.info("weak_answers_lost_race", session_id=str(session_id))
            return await self._kept(session_id)

        return answers

    async def _settled(self, session_id: uuid.UUID) -> Session:
        """The room, once billing has closed on it.

        `settled` rather than merely finished: §4.1 puts settlement first —
        the panel finishes, the session settles, then debrief — and reading a
        room that is still live would rank a conversation still happening.
        """
        session = await self._db.get(Session, session_id)
        if session is None:
            raise SessionNotFound(session_id=str(session_id))
        if session.state is not SessionState.SETTLED:
            raise SessionNotSettled(
                session_id=str(session_id), state=session.state.value
            )
        return session

    async def _transcript(self, session_id: uuid.UUID) -> tuple[Said, ...]:
        """The room, in order, both sides.

        Ordered by `ordinal` and never by `said_at`: lines are written as they
        are said, so two can share a clock reading, and a transcript that
        occasionally transposes a question and its answer would have the model
        ranking a room that did not happen.
        """
        rows = await self._db.execute(
            select(TranscriptLine)
            .where(TranscriptLine.session_id == session_id)
            .order_by(TranscriptLine.ordinal)
        )
        return tuple(
            Said(
                speaker=row.speaker,
                text=row.text,
                disputed=row.disputed,
                chosen_by=row.chosen_by,
            )
            for row in rows.scalars()
        )
