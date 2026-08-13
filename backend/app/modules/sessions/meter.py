"""The meter — charges live interrogation as it is consumed.

A periodic sweep rather than a timer per room. A per-session task lives in one
process, so a crash, a restart, or an ordinary deploy would stop billing every
room that was open while the voice provider carried on charging us — and the
reaper would not catch it, because those sessions still look perfectly alive.

`tick_index` is derived from how long the interrogation span has been open
rather than counted by the sweep. That is what makes the sweep stateless: two
workers reach the same index for the same room, a sweep that missed a beat
catches up on the next pass, and one that runs twice is a no-op because the
ledger is already idempotent on `(session_id, tick_index)`.

Nothing here records progress. The tick doubles as the heartbeat, but the
heartbeat is the *client* proving it is still there — a server-side sweep
touching `last_progress_at` would keep every abandoned room looking alive and
quietly disarm the reaper.
"""

from __future__ import annotations

import uuid
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.errors import FlintroomError
from app.core.logging import get_logger
from app.modules.billing.service import LedgerService
from app.modules.sessions.models import Session, SessionPhaseSpan
from app.modules.sessions.schemas import (
    IDLE_LIMIT,
    SESSION_LIMIT,
    TICK_INTERVAL,
    EndReason,
    SessionPhase,
    SessionState,
)
from app.modules.sessions.service import SessionService
from app.modules.sessions.settlement import SettlementService

#: Seconds in one billable interval, as the ledger wants them.
TICK_SECONDS = int(TICK_INTERVAL.total_seconds())

#: The session cap counted in ticks. Expressed in the sweep's own unit so the
#: cap is checked against the same derived index everything else here uses,
#: rather than against a second reading of the clock that could disagree.
CAP_TICKS = int(SESSION_LIMIT / TICK_INTERVAL)

#: The idle cutoff in seconds, to compare against what the query returns.
IDLE_SECONDS = IDLE_LIMIT.total_seconds()

log = get_logger(__name__, tag="billing")


class _Room(NamedTuple):
    """A live interrogation and what it owes.

    Columns rather than mapped rows, for the reason given in the reaper: this
    sweep rolls back on contention, and a rollback expires every ORM object
    attached to the session.
    """

    id: uuid.UUID
    user_id: uuid.UUID
    ticks_due: int
    idle_seconds: float


class MeterService:
    """Charges every live room for the intervals it has completed."""

    def __init__(self, db: AsyncSession, actor: ActorContext | None = None) -> None:
        self._db = db
        self._actor = actor or ActorContext.system()
        self._sessions = SessionService(db, self._actor)
        self._ledger = LedgerService(db, self._actor)
        self._settlement = SettlementService(db, self._actor)

    async def sweep(self) -> None:
        """One pass over every live room."""
        rooms = await self._live_rooms()
        skipped = 0
        for room in rooms:
            try:
                await self._charge_due(room)
                await self._enforce_caps(room)
            except FlintroomError as exc:
                skipped += 1
                # The room closed under us — the user pressed End, or the reaper
                # got there first. Ordinary contention, and it must not end the
                # batch: the rooms after this one are still running and still
                # costing us money, and deferring them only means the next sweep
                # meets the same contention with more to bill.
                # Hygiene rather than something a test forces today: the
                # refusals reached from here are raised before they mutate
                # anything. It stands so that the next error raised mid-write
                # cannot leak half a change into the following room's commit —
                # which is exactly the bug the reaper's sweep already had.
                await self._db.rollback()
                log.warning(
                    "meter_skipped",
                    user_id=str(room.user_id),
                    session_id=str(room.id),
                    code=exc.code,
                )

        # One line per pass, whether or not anything happened. This is the
        # series that answers "were we billing at all last Tuesday" and "how
        # many rooms were open when the bill spiked" — neither of which can be
        # reconstructed from the per-room lines, because the absence of those
        # is indistinguishable from a sweep that never ran.
        log.info("meter_swept", rooms=len(rooms), skipped=skipped)

    async def _charge_due(self, room: _Room) -> None:
        """Charge every interval this room has completed and not yet paid for.

        Resumes from what the ledger has already recorded rather than replaying
        from zero. Replaying was correct — every repeat is refused as a
        duplicate — but it costs one round trip per interval already billed, so
        a room at the session cap would re-ask forty-eight questions it knows
        the answer to, on every sweep, for every room.

        This is still not a cursor. Nothing here remembers anything between
        sweeps; the resume point is read back from the entries themselves, so a
        worker that died mid-batch leaves nothing to go stale.
        """
        charged = await self._ledger.ticks_charged(session_id=room.id)
        for index in range(charged, room.ticks_due):
            await self._ledger.charge_tick(
                user_id=room.user_id,
                session_id=room.id,
                tick_index=index,
                seconds=TICK_SECONDS,
            )

    async def _enforce_caps(self, room: _Room) -> None:
        """Decide whether this room has to stop, having billed what it owes.

        Separate from the billing above because the caps are about elapsed time,
        not about whether this particular sweep happened to charge anything. Run
        only when a tick was due, the grace clock would be checked solely on
        sweeps that coincided with an interval boundary — so a room could sit
        past its cap for as long as it took the next one to elapse.
        """
        if room.ticks_due == 0:
            # Not yet a full interval old. Nothing has been billed, so there is
            # no overdraft to be in and no length to have exceeded.
            return

        # Idle is checked first because it is the ending that happened first.
        # An abandoned room reaches the idle cutoff at ninety seconds; if it is
        # still open twelve minutes later, that is a sweep that was down, not a
        # user who used their whole session. The order is not bookkeeping — it
        # decides whether they are refunded, and only this ending refunds.
        if room.idle_seconds >= IDLE_SECONDS:
            await self._close(room, EndReason.IDLE_TIMEOUT)
            return

        if room.ticks_due >= CAP_TICKS:
            # Before grace, for the same reason: a room that ran its full length
            # ended because it ran its full length. An end reason of `grace_cap`
            # on a twelve-minute session would send every cost report looking
            # for an overdraft that was incidental to it.
            await self._close(room, EndReason.SESSION_CAP)
            return

        balance = await self._ledger.balance(user_id=room.user_id)
        if balance.total_seconds >= 0:
            # Back in the black, so whatever grace was running is over. The
            # other branch of one decision, asked on every sweep — see
            # `SessionService.leave_grace`.
            await self._sessions.leave_grace(session_id=room.id)
        elif await self._sessions.enter_grace(session_id=room.id):
            await self._close(room, EndReason.GRACE_CAP)

    async def _close(self, room: _Room, end_reason: EndReason) -> None:
        """End the room and settle it in the same pass.

        The same sequence the End button runs, and deliberately the same code:
        a cap firing and a user tapping End differ in the reason recorded, not
        in what has to happen to the money.
        """
        await self._settlement.close(session_id=room.id, end_reason=end_reason)
        log.info(
            "room_closed_by_meter",
            user_id=str(room.user_id),
            session_id=str(room.id),
            end_reason=end_reason.value,
        )

    async def _live_rooms(self) -> list[_Room]:
        """Every active session, with the number of intervals it has completed.

        The arithmetic is Postgres', not ours: the span's `started_at` was
        written with the database's clock, and a worker whose own clock has
        drifted would bill a room for time it has not run.
        """
        elapsed = func.extract("epoch", func.now() - SessionPhaseSpan.started_at)
        # Silence is measured from the span when the user has never spoken: a
        # room nobody has said anything in has been quiet since it opened, and
        # that is the abandoned room this is looking for.
        quiet_since = func.extract(
            "epoch",
            func.now()
            - func.coalesce(
                Session.last_user_speech_at, SessionPhaseSpan.started_at
            ),
        )
        result = await self._db.execute(
            select(
                Session.id,
                Session.user_id,
                func.floor(elapsed / TICK_SECONDS),
                quiet_since,
            )
            .join(SessionPhaseSpan, SessionPhaseSpan.session_id == Session.id)
            .where(
                Session.state == SessionState.ACTIVE,
                SessionPhaseSpan.phase == SessionPhase.INTERROGATION,
                SessionPhaseSpan.ended_at.is_(None),
            )
        )
        return [
            _Room(id, user_id, int(due), float(quiet))
            for id, user_id, due, quiet in result.all()
        ]
