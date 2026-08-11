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

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.logging import get_logger
from app.modules.billing.schemas import EntryReason
from app.modules.billing.service import LedgerService
from app.modules.sessions.models import Session
from app.modules.sessions.schemas import EndReason, SessionState
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
#: `idle_timeout` is the one deliberate gap. It owes a refund — but of the idle
#: window only, not the session, and nothing yet records when the user last
#: spoke. Refunding the whole session would hand back a rehearsal that worked
#: right up until the user walked away. Wire it when idle detection lands and
#: has a timestamp to offer; see docs/minutes-ledger-and-sessions.md Part 2.
REFUND_REASONS: dict[EndReason | None, EntryReason] = {
    EndReason.PROVIDER_FAILURE: EntryReason.REFUND_PROVIDER_FAILURE,
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
                user_id=session.user_id, session_id=session.id, reason=reason
            )

        await self._ledger.forgive_overdraft(
            user_id=session.user_id, session_id=session.id
        )

        return await self._sessions.settle(session_id=session_id)
