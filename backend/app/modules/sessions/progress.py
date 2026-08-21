"""Whether somebody is getting better, without telling them how they spoke.

Asked for directly: *"user is meant to track their development — how would they
if they were not scored per session"*. The answer had been "no scores", and that
was over-broad. `Product.md:15` and `:392` refuse a **delivery-metrics** scorer —
*"Delivery-metrics scoring is the commodity layer and is not the product"* — and
say nothing against a figure about whether an *argument* held. §4.1 states the
product's purpose is improvement, which is not servable by refusing to describe
one.

**Everything here is arithmetic over what the debrief already stored.** No model
call, no new judgement, and deliberately so: the one judgement in this pipeline
is #57's reading of a room, and a second opinion layered on top of it would be a
second thing to be wrong about the same session.

**The rung travels with every figure and is never separable.** Difficulty
escalates (#55), so a count of what got past somebody can rise while they
improve. A number shown without the level it was earned at would tell an
improving presenter they are getting worse — the one message this must never
send.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.calibration import PRESENTER_AT_FAULT
from app.agents.context import USER
from app.agents.weakness import Weakness
from app.modules.sessions.models import Session, SessionWeakAnswer, TranscriptLine
from app.modules.sessions.rehearsals import names_of


@dataclass(frozen=True, slots=True)
class RoomHeld:
    """One assessed room: what it put to them, what they held, and how hard it was.

    `held` and `challenged` are meaningless apart from `level`, which is why all
    three are on one object rather than in three lists a caller could pair up
    wrongly.
    """

    session_id: uuid.UUID

    #: The rehearsal this room belongs to — its own id unless it repeats another.
    #:
    #: Never null, though the column behind it is. `COALESCE(rehearsal_id, id)`
    #: is applied here so the nullable-for-migration-safety fact stops at this
    #: boundary; letting it travel would put a null branch in every consumer.
    rehearsal: uuid.UUID

    #: What the presenter calls that rehearsal, or null if nobody named it.
    #:
    #: The group's name rather than this room's — the newest name given to any
    #: room in the lineage, so the rooms run before somebody thought to name the
    #: thing report it too.
    rehearsal_name: str | None

    started_at: datetime
    #: Challenges the presenter actually had a turn at. A question a colleague
    #: talked over is not one, so it is in neither term — see `read`.
    challenged: int
    held: int
    #: The rung this room ran at, or null for a room that predates the ladder.
    level: int | None


@dataclass(frozen=True, slots=True)
class Progress:
    """Everything a history screen is allowed to say.

    No total, no average, no streak. A single lifetime figure is the shape that
    invites optimising the figure, and an average across rungs is arithmetic
    over incomparable rooms.
    """

    #: Newest first, so the room somebody just left is the one they see.
    rooms: tuple[RoomHeld, ...] = ()
    #: `(weakness, rooms it happened in)`, commonest first. Faults only.
    habits: tuple[tuple[str, int], ...] = ()
    #: `(archetype, rooms they caught you in)`, commonest first.
    askers: tuple[tuple[str, int], ...] = ()


class ProgressService:
    """Reads a history out of rooms that have already been assessed."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def read(self, *, user_id: uuid.UUID) -> Progress:
        """Every assessed room for this account, newest first.

        **Assessed, not merely settled.** `sessions.debriefed_at` is the
        difference, and it is the whole reason that column carries a fact the
        weak-answer rows cannot: a room with nothing wrong and a room nobody
        opened are both zero findings. Counting the second would report a clean
        sweep for a room the product never read.

        Three queries and no joins across them, because the denominator lives in
        a different table from the numerator and a single statement would be a
        correlated count nobody could read. None is on a hot path — this is a
        screen somebody opens, not something a room does.
        """
        rooms = (
            await self._db.execute(
                select(
                    Session.id,
                    func.coalesce(Session.rehearsal_id, Session.id).label("rehearsal"),
                    Session.started_at,
                    Session.difficulty_level,
                )
                .where(
                    Session.user_id == user_id,
                    Session.debriefed_at.is_not(None),
                )
                .order_by(Session.started_at.desc())
            )
        ).all()

        if not rooms:
            return Progress()

        ids = [room.id for room in rooms]

        # Every line the panel put to them, follow-ups included — the same count
        # `DebriefService` takes for calibration. A second rule about what a
        # challenge is would drift from the one that moves the ladder.
        # `.tuples()` because a `Row` is tuple-like and is not a tuple, and
        # `dict` takes pairs.
        asked = dict(
            (
                await self._db.execute(
                    select(TranscriptLine.session_id, func.count())
                    .where(
                        TranscriptLine.session_id.in_(ids),
                        TranscriptLine.speaker != USER,
                    )
                    .group_by(TranscriptLine.session_id)
                )
            )
            .tuples()
            .all()
        )

        findings = (
            await self._db.execute(
                select(
                    SessionWeakAnswer.session_id,
                    SessionWeakAnswer.weakness,
                    SessionWeakAnswer.asked_by,
                ).where(SessionWeakAnswer.session_id.in_(ids))
            )
        ).all()

        # One query for every name this account has given, folded into the rooms
        # below. A lineage's name lives on whichever of its rooms carried one,
        # so it cannot be read off the row it belongs to.
        named = await names_of(self._db, user_id=user_id)

        return Progress(
            rooms=tuple(_held(room, named, asked, findings) for room in rooms),
            habits=_by_room(
                (found.session_id, found.weakness)
                for found in findings
                if _at_fault(found.weakness)
            ),
            askers=_by_room(
                (found.session_id, found.asked_by)
                for found in findings
                if _at_fault(found.weakness)
            ),
        )


def _held(room, named, asked, findings) -> RoomHeld:
    """One room's arithmetic, with both exclusions applied.

    A question the room took away leaves **both** terms. It is not a failure —
    #56 — and it is not a success either, because nobody answered it. Counting
    it as held would be the same false comfort as counting it as fumbled is a
    false accusation.
    """
    mine = [found for found in findings if found.session_id == room.id]
    taken = sum(1 for found in mine if not _at_fault(found.weakness))
    fumbled = len(mine) - taken

    challenged = max(0, asked.get(room.id, 0) - taken)

    return RoomHeld(
        session_id=room.id,
        rehearsal=room.rehearsal,
        rehearsal_name=named.get(room.rehearsal),
        started_at=room.started_at,
        challenged=challenged,
        held=max(0, challenged - fumbled),
        level=room.difficulty_level,
    )


def _at_fault(weakness: Weakness | str) -> bool:
    """Whether this one was the presenter's doing.

    Through `calibration.PRESENTER_AT_FAULT` rather than a list of its own. That
    set already decides what moves the difficulty ladder, and two answers to
    "was this their fault" is how a screen and a dial come to disagree about the
    same room.
    """
    return Weakness(weakness) in PRESENTER_AT_FAULT


def _by_room(pairs) -> tuple[tuple[str, int], ...]:
    """How many *rooms* each thing happened in, commonest first.

    Rooms rather than findings, because a habit is a thing that recurs. Two
    evasive answers in one bad afternoon is one room where it happened, and
    counting findings would let a single disastrous session read as a pattern.

    Ties broken by name so the order is stable between reads — a list that
    reshuffled under somebody would look like their history had changed.
    """
    seen: dict[str, set] = {}
    for session_id, thing in pairs:
        key = thing.value if isinstance(thing, Weakness) else str(thing)
        seen.setdefault(key, set()).add(session_id)

    counted = Counter({key: len(rooms) for key, rooms in seen.items()})
    return tuple(sorted(counted.items(), key=lambda item: (-item[1], item[0])))
