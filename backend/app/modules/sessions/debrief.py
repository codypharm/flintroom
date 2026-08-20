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

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.calibration import calibrate
from app.agents.difficulty import GENTLE
from app.agents.weakness import WeakAnswer, Weakness, WeaknessReader, weak_answers
from app.core.errors import (
    RoomBroke,
    RoomHasNoQuestions,
    SessionNotFound,
    SessionNotSettled,
)
from app.core.logging import get_logger
from app.modules.billing.models import Account
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
        if await self._read_already(session_id):
            return await self._kept(session_id)

        # **The rows outrank the marker, and this is the second gate rather
        # than a belt on the first.** `debriefed_at` and these rows are two
        # records of one fact, and on 2026-08-20 they disagreed on a live room:
        # the marker had been cleared and the rows had not. The service then
        # bought a fresh reasoning reading, claimed the marker, and tried to
        # insert rank 0 over a rank 0 that was already there —
        # `UniqueViolationError`, unhandled, 500. Every later open would have
        # repeated it, and paid for another reading each time.
        #
        # The kept rows win because they are what the user was SHOWN. A second
        # reading of the same transcript reorders, which is precisely the
        # failure `test_a_room_is_read_once_and_the_answer_is_kept` exists to
        # prevent — and the prep sheet somebody screenshotted was built from
        # these.
        #
        # One extra SELECT on the cold path only. The warm path returns at the
        # marker above and never reaches here.
        if kept := await self._kept(session_id):
            await self._mark_read(session_id)
            log.info("weak_answers_marker_repaired", session_id=str(session_id))
            return kept

        session = await self._settled(session_id)

        if session.end_reason is EndReason.PROVIDER_FAILURE:
            raise RoomBroke(session_id=str(session_id))

        transcript = await self._transcript(session_id)

        # Every line the panel put to them, follow-ups included: a press is a
        # second thing to handle, not a repeat of the first, and the presenter
        # had to answer it either way.
        questions = sum(1 for line in transcript if line.speaker != USER)

        if not questions:
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

        return await self._keep(
            session_id,
            ranked.answers,
            user_id=session.user_id,
            questions=questions,
        )

    async def _read_already(self, session_id: uuid.UUID) -> bool:
        """Whether anybody has read this room yet.

        A column rather than "are there any rows", because an empty list is a
        real answer — the model found nothing wrong — and the two are
        indistinguishable from the rows alone.
        """
        mark = await self._db.execute(
            select(Session.debriefed_at).where(Session.id == session_id)
        )
        return mark.scalar_one_or_none() is not None

    async def _mark_read(self, session_id: uuid.UUID) -> None:
        """Put back a marker whose rows outlived it.

        Answering is not enough. Left null, every open would take the recovery
        path above forever — and `progress.py` counts *assessed* rooms by this
        column, so the room would stay missing from somebody's record while
        plainly having been debriefed.

        Guarded on `IS NULL` like the claim in `_keep`, so a device that reaches
        here at the same moment as a real first read cannot overwrite the
        winner's timestamp.
        """
        await self._db.execute(
            update(Session)
            .where(Session.id == session_id, Session.debriefed_at.is_(None))
            .values(debriefed_at=func.now())
        )
        await self._db.commit()

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
                next_time=row.next_time,
            )
            for row in rows.scalars()
        )

    async def _keep(
        self,
        session_id: uuid.UUID,
        answers: tuple[WeakAnswer, ...],
        *,
        user_id: uuid.UUID,
        questions: int,
    ) -> tuple[WeakAnswer, ...]:
        """Write the list, move the rung, or accept the one that got there first.

        Two devices opening the debrief at the same moment both read the room
        and both try to write. That is a wasted call rather than a fault, and
        the loser must hand back the winner's list rather than its own — the
        two are different readings of the same transcript, and a user whose
        second device showed a different ranking would be right to distrust
        both.

        **The rung moves in the same transaction, and only on the winning
        write** (#55). Bound to the insert rather than guarded separately, for
        two reasons. The reading and the level it produces are one fact about
        one room, so a separate guard is a second thing that can disagree. And
        the primary key on `(session_id, rank)` is already the serialization: a
        second opener loses the insert and never reaches the update, so nothing
        needs a lock on the account row to keep two devices from escalating
        somebody twice for one session.
        """
        claimed = await self._db.execute(
            update(Session)
            .where(Session.id == session_id, Session.debriefed_at.is_(None))
            .values(debriefed_at=func.now())
        )
        if not claimed.rowcount:
            # Somebody else read this room first. Their transaction held the
            # row lock until it committed, so this update re-evaluated the
            # condition afterwards and matched nothing — which is the whole
            # guard, and it needs no advisory lock of its own.
            await self._db.rollback()
            log.info("weak_answers_lost_race", session_id=str(session_id))
            return await self._kept(session_id)

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
                next_time=answer.next_time,
            )
            for rank, answer in enumerate(answers)
        )

        moved = calibrate(
            await self._level_of(user_id), weak=answers, questions=questions
        )
        await self._db.execute(
            update(Account)
            .where(Account.user_id == user_id)
            .values(difficulty_level=moved)
        )

        await self._db.commit()

        log.info(
            "difficulty_calibrated",
            user_id=str(user_id),
            session_id=str(session_id),
            level=moved,
            questions=questions,
        )
        return answers

    async def _level_of(self, user_id: uuid.UUID) -> int:
        """The rung this account is on now.

        Read inside the same transaction as the write above it, which is what
        makes the read-modify-write safe without a lock: the insert that races
        this one fails on the primary key before it ever gets here.
        """
        stored = await self._db.execute(
            select(Account.difficulty_level).where(Account.user_id == user_id)
        )
        return stored.scalar_one_or_none() or GENTLE

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

    async def pressed(self, *, session_id: uuid.UUID) -> str | None:
        """How this room compared to the one before it, or nothing.

        The comparison the debrief's one sentence is made of. Reads the rung
        each room *ran at* rather than the rung the account is on now — by the
        time anybody opens a debrief the account may have moved, and comparing
        against a number that has since changed would describe a room nobody
        was in.

        The previous room is the last one before this that actually happened:
        settled, and with a rung recorded. Sessions started and never joined
        have no `difficulty_level` and are skipped, because they are not rooms.

        Null rather than a third word when the rung is unchanged. Nothing
        happened, and a screen already carrying weak answers and a coach does
        not need a sentence saying so.
        """
        this = await self._db.get(Session, session_id)
        if this is None or this.difficulty_level is None:
            return None

        before = await self._db.execute(
            select(Session.difficulty_level)
            .where(
                Session.user_id == this.user_id,
                Session.difficulty_level.is_not(None),
                Session.settled_at.is_not(None),
                Session.settled_at < this.settled_at,
            )
            .order_by(Session.settled_at.desc())
            .limit(1)
        )
        last = before.scalar_one_or_none()
        if last is None or last == this.difficulty_level:
            return None

        return "harder" if this.difficulty_level > last else "easier"
