"""Settlement — the join between the session state machine and the ledger.

Kept out of both `SessionService` and `LedgerService` on purpose. Settlement is
where the two meet, and putting it inside either one makes that module carry the
other's rules: the state machine would grow refund policy, or the ledger would
grow opinions about end reasons. This is also where §4.3's `session_costs`
telemetry will attach, which is a third concern belonging to neither.

Retry safety comes from the ledger, not from a lock. Every write below is
idempotent on a key derived from the session, so a settlement that dies partway
leaves the session in `finalizing` for the reaper to run again — and the second
run reaches the same end state without paying anything twice.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.logging import get_logger
from app.modules.billing.schemas import EntryReason
from app.modules.billing.service import LedgerService
from app.modules.sessions.models import Session, SessionPhaseSpan
from app.modules.sessions.schemas import (
    TICK_INTERVAL,
    EndReason,
    SessionPhase,
    SessionState,
)
from app.modules.sessions.service import SessionService

#: Which endings owe the user their minutes back, and under which typed reason.
#: A mapping rather than a chain of conditionals so that adding an end reason
#: forces a deliberate answer to "does this one refund?" — the omission that
#: would otherwise show up as a user quietly charged for our outage.
#:
#: Absent keys refund nothing, and each is absent for a reason:
#: `user_ended`, `session_cap` and `grace_cap` all delivered the time the user
#: paid for, and `client_disconnect` is already correct because ticks are
#: charged in arrears. `provisioning_failed` never reaches settlement at all.
#:
#: `idle_timeout` refunds the silent window only, not the session — the room
#: worked right up until the user stopped answering, and handing back a
#: rehearsal they used would be a different product decision than "do not charge
#: for time nobody received".
REFUND_REASONS: dict[EndReason | None, EntryReason] = {
    EndReason.PROVIDER_FAILURE: EntryReason.REFUND_PROVIDER_FAILURE,
    EndReason.IDLE_TIMEOUT: EntryReason.REFUND_IDLE,
}

log = get_logger(__name__, tag="billing")


class SettlementService:
    """Closes billing on a session that has stopped running."""

    def __init__(self, db: AsyncSession, actor: ActorContext | None = None) -> None:
        self._db = db
        self._sessions = SessionService(db, actor)
        self._ledger = LedgerService(db, actor)

    async def settle(self, *, session_id: uuid.UUID) -> Session:
        """Write the money owed, then close the session.

        Money first, state last. The state move is what releases the lock and
        marks the session settled, so doing it first would leave a crash looking
        like a completed settlement — and the refund would never be written.
        """
        session = await self._sessions.get(session_id=session_id)
        # Before any money moves. The same check happens inside the state move
        # at the end, but by then the writes below are committed — and grace
        # forgiveness against a still-running session resets the overdraft the
        # grace cap watches, so the room would keep ticking with its debt wiped.
        self._sessions.require_transition(session, SessionState.SETTLED)

        if (reason := REFUND_REASONS.get(session.end_reason)) is not None:
            await self._ledger.refund_session(
                user_id=session.user_id,
                session_id=session.id,
                reason=reason,
                from_index=await self._first_unserved_tick(session, reason),
            )

        await self._ledger.forgive_overdraft(
            user_id=session.user_id, session_id=session.id
        )

        return await self._sessions.settle(session_id=session_id)

    async def _first_unserved_tick(
        self, session: Session, reason: EntryReason
    ) -> int:
        """The tick from which the user stopped receiving what they paid for.

        Zero for every reason but idle: a provider failure means the room was
        not delivering from the moment it broke, and settlement is only reached
        with that reason once it has. Idle is the one ending where the earlier
        part of the session worked exactly as sold.

        The straddling tick — the one running when they went quiet — is refunded
        whole rather than split. It rounds in the user's favour by at most one
        interval, matching how the ledger rounds everywhere else, and it avoids
        prorating a single tick back across whichever buckets it drew from.
        """
        if reason is not EntryReason.REFUND_IDLE:
            return 0
        if session.last_user_speech_at is None:
            # They never said a word, so no part of this room was received.
            return 0

        started_at = await self._interrogation_started_at(session.id)
        silent_from = (session.last_user_speech_at - started_at).total_seconds()
        return max(int(silent_from // TICK_INTERVAL.total_seconds()), 0)

    async def _interrogation_started_at(self, session_id: uuid.UUID) -> datetime:
        """When the metered window opened.

        Read from the span rather than from `sessions.started_at`, which marks
        spin-up: the tick index everything here is counted in is measured from
        the span, and mixing the two would shift every index by however long the
        voice channel took to come up.
        """
        result = await self._db.execute(
            select(SessionPhaseSpan.started_at)
            .where(
                SessionPhaseSpan.session_id == session_id,
                SessionPhaseSpan.phase == SessionPhase.INTERROGATION,
            )
            .order_by(SessionPhaseSpan.started_at)
            .limit(1)
        )
        return result.scalar_one()
