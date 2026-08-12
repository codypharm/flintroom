"""The reaper — the janitor for sessions no user action will ever resolve.

Every non-terminal state holds the user's one-live-session lock, so a session
left in one is not merely untidy: the user cannot start another rehearsal, and
has no button that would clear it. The client that would otherwise retry has
usually already been told the session ended, or has gone away entirely.

Timeouts are compared against Postgres' clock rather than the process's. The
timestamps being compared are written with `func.now()`, and the reaper is
expected to run on more than one worker — mixing an app clock into that means a
skewed worker reaps live sessions early, which is a user thrown out of a
rehearsal they are still in.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.errors import FlintroomError
from app.core.logging import get_logger
from app.modules.audit_log.schemas import AuditEventType
from app.modules.audit_log.service import AuditService
from app.modules.sessions.models import Session
from app.modules.sessions.schemas import TICK_INTERVAL, EndReason, SessionState
from app.modules.sessions.service import SessionService
from app.modules.sessions.settlement import SettlementService

#: How long agent spin-up may take before we call it dead. Generous against a
#: slow provider, but bounded in seconds rather than minutes: nothing is billed
#: in `provisioning`, so the only thing the wait costs is the user's next
#: session — see docs/minutes-ledger-and-sessions.md Part 2.
PROVISIONING_TIMEOUT = timedelta(seconds=60)

#: Three missed ticks. The billing tick doubles as the heartbeat, so silence
#: this long means the client is gone rather than quiet — and there is no
#: reconnect window, because holding a voice agent open costs money to talk to
#: an empty room (docs/minutes-ledger-and-sessions.md Part 2, Detection).
ORPHAN_TIMEOUT = 3 * TICK_INTERVAL

#: How long a settlement may be in flight before we assume it died. Settlement
#: is a handful of database round trips, so this is generous by orders of
#: magnitude — but it has to stay well clear of a settlement that is merely
#: slow, because a sweep racing a live one produces two attempts at the same
#: close. The money survives that (every write is idempotent); the wasted work
#: and the duplicate audit rows are avoidable. Short, because the user is locked
#: out of starting anything until this resolves.
FINALIZING_TIMEOUT = timedelta(seconds=30)

log = get_logger(__name__, tag="sessions")


class _Stalled(NamedTuple):
    """The little a sweep needs to know about a session it is about to end."""

    id: uuid.UUID
    user_id: uuid.UUID
    state: SessionState
    end_reason: EndReason | None


class ReaperService:
    """Ends sessions that stopped making progress."""

    def __init__(self, db: AsyncSession, actor: ActorContext | None = None) -> None:
        self._db = db
        # `REAPER`, not `SYSTEM`. Everything written under this actor — audit
        # rows here, ledger rows once settlement runs from a sweep — happened
        # to a user who was not there, which is the first thing worth knowing
        # when one of them is disputed.
        self._actor = actor or ActorContext.reaper()
        self._sessions = SessionService(db, self._actor)
        self._settlement = SettlementService(db, self._actor)
        self._audit = AuditService(db, self._actor, tag="sessions")

    async def reap(self) -> None:
        """One sweep, in lifecycle order. Safe to run alongside real users."""
        reaped = 0
        skipped = 0
        for state, timeout, close in (
            (SessionState.PROVISIONING, PROVISIONING_TIMEOUT, self._abandon),
            (SessionState.ACTIVE, ORPHAN_TIMEOUT, self._disconnect),
            (SessionState.FINALIZING, FINALIZING_TIMEOUT, self._finish_settling),
        ):
            for session in await self._stalled(state, timeout):
                try:
                    await close(session)
                    reaped += 1
                except FlintroomError as exc:
                    skipped += 1
                    # The user got there first: they ended the session, or
                    # another worker reaped it, between our select and our
                    # write. Ordinary contention, and it must not end the
                    # batch — the sessions after this one are still stuck, and
                    # abandoning them means the next sweep meets the same
                    # contention with more work to do.
                    #
                    # The rollback also discards the audit row staged inside
                    # `close`, so a reaping that did not happen leaves no row
                    # claiming it did. Anything that is not one of our own
                    # errors is a bug and is left to propagate.
                    await self._db.rollback()
                    log.warning(
                        "reap_skipped",
                        session_id=str(session.id),
                        user_id=str(session.user_id),
                        from_state=state.value,
                        code=exc.code,
                    )

        # One line per pass, even an empty one. A sweep that reaps nothing is
        # the normal case and the reason to record it: without this, "the reaper
        # has not run since Friday" looks exactly like "nothing needed reaping."
        log.info("reaper_swept", reaped=reaped, skipped=skipped)

    async def _abandon(self, session: _Stalled) -> None:
        """Spin-up never finished. Nothing was billed, so nothing is settled —
        `failed` keeps a room that never opened out of the cost reports."""
        self._mark_reaped(session, EndReason.PROVISIONING_FAILED)
        await self._sessions.fail(
            session_id=session.id, end_reason=EndReason.PROVISIONING_FAILED
        )

    async def _disconnect(self, session: _Stalled) -> None:
        """The client stopped answering. Closed and settled in one pass.

        Splitting it across two sweeps would hold the user's lock for another
        interval for no reason, and this is somebody whose train went into a
        tunnel rather than somebody who did anything wrong.
        """
        self._mark_reaped(session, EndReason.CLIENT_DISCONNECT)
        await self._sessions.begin_finalizing(
            session_id=session.id, end_reason=EndReason.CLIENT_DISCONNECT
        )
        await self._settlement.settle(session_id=session.id)

    async def _finish_settling(self, session: _Stalled) -> None:
        """Settlement died partway. The end reason was decided when the session
        stopped, and settlement failing afterwards does not change why."""
        self._mark_reaped(session, session.end_reason)
        await self._settlement.settle(session_id=session.id)

    def _mark_reaped(self, session: _Stalled, end_reason: EndReason | None) -> None:
        """Stage the record that the system, not the user, ended this.

        Staged rather than recorded so it lands in the same transaction as the
        change it explains — the caller below commits both. This is the ending
        with no request behind it and the one most likely to be disputed, so the
        row must not be able to exist without the change, or the change without
        the row.
        """
        self._audit.stage(
            AuditEventType.SESSION_REAPED,
            user_id=session.user_id,
            session_id=session.id,
            from_state=session.state.value,
            end_reason=end_reason.value if end_reason else None,
        )

    async def _stalled(
        self, state: SessionState, timeout: timedelta
    ) -> list[_Stalled]:
        """Sessions in `state` that have made no progress for `timeout`.

        Columns, not ORM rows, and deliberately so. A rollback expires every
        object attached to the session, and the reaper rolls back routinely —
        once per lost race. Holding mapped rows across that means the *next*
        session in the batch lazy-loads its own attributes mid-sweep, which in
        async code surfaces as `MissingGreenlet` rather than as anything
        resembling the real cause. The services reload what they need anyway.
        """
        result = await self._db.execute(
            select(
                Session.id, Session.user_id, Session.state, Session.end_reason
            ).where(
                Session.state == state,
                Session.last_progress_at < func.now() - timeout,
            )
        )
        return [_Stalled(*row) for row in result.all()]
