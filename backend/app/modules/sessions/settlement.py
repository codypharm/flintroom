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

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.logging import get_logger
from app.modules.billing.models import Account
from app.modules.billing.schemas import EntryReason
from app.modules.billing.service import LedgerService
from app.modules.voice.costs import SessionCost
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

    async def close(self, *, session_id: uuid.UUID, end_reason: EndReason) -> Session:
        """Stop the meter and settle, in one pass.

        The two halves are never useful apart — a room told to stop and left
        `finalizing` still holds the user's lock, so the debrief §4.1 hands them
        to cannot start until the reaper next runs. Kept here rather than in a
        handler or in the meter because it is the sequence itself that has to be
        right: money is written between the two, and a caller that reordered
        them would settle a room still being billed.
        """
        await self._sessions.begin_finalizing(
            session_id=session_id, end_reason=end_reason
        )
        return await self.settle(session_id=session_id)

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

        if await self._never_heard(session):
            # The zero-audio refund (docs/reconnect.md decision 5), and it
            # replaces rather than joins the reason-mapped refund below: a
            # room that heard nothing delivered nothing, so the full refund
            # subsumes any partial one — and writing both would pay the
            # overlapping ticks back twice.
            await self._ledger.refund_session(
                user_id=session.user_id,
                session_id=session.id,
                reason=EntryReason.REFUND_UNHEARD,
            )
        elif (reason := REFUND_REASONS.get(session.end_reason)) is not None:
            await self._ledger.refund_session(
                user_id=session.user_id,
                session_id=session.id,
                reason=reason,
                from_index=await self._first_unserved_tick(session, reason),
            )

        await self._ledger.forgive_overdraft(
            user_id=session.user_id, session_id=session.id
        )
        await self._record_cost(session)

        return await self._sessions.settle(session_id=session_id)

    async def _never_heard(self, session: Session) -> bool:
        """Did this room bill time without ever processing a second of STT?

        The cost row is the witness: `SpendRecorder` accumulates STT seconds
        turn by turn, and the opening statement gives the presenter the floor
        first — so a genuinely working room cannot reach settlement at zero.
        An absent row is the same testimony as a zero, from a room in which no
        turn ever ran. Exactly zero, deliberately: "very little" is a
        judgement about a partially working room; zero is a fact.
        """
        stt = await self._db.scalar(
            select(SessionCost.stt_seconds_processed).where(
                SessionCost.session_id == session.id
            )
        )
        return not stt

    async def _record_cost(self, session: Session) -> None:
        """Leave one `session_costs` row behind (Product.md §4.3).

        Here rather than in the meter, because the interrogation window is only
        final once the room has stopped. A row accumulated tick by tick would
        need correcting by every refund and grace write-off, and §4.3's
        acceptance test — agreement with the provider invoice within 10% —
        cannot be run against a figure that was true at some point mid-session.

        Idempotent by primary key, like everything else settlement writes: the
        reaper re-runs a settlement that died partway, and a second cost row for
        one session would quietly double that session in every per-minute
        average computed from this table.

        Updates its own columns on conflict rather than doing nothing. The row
        no longer belongs to settlement alone — `SpendRecorder` creates it on
        the first turn — so a do-nothing upsert would discard the duration of
        every session in which anybody actually spoke, and keep it only for
        rooms where the panel never said a word. That failure is close to
        invisible: the table fills, the rows look plausible, and the denominator
        of every per-minute figure is zero for exactly the sessions worth
        measuring.

        Re-running is still safe. These three are computed from the session's
        final state rather than accumulated, so writing them twice writes the
        same values twice — unlike the consumption columns, which `SpendRecorder`
        adds to and settlement must never touch.
        """
        seconds = await self._interrogation_seconds(session.id)
        tier = await self._tier(session.user_id)
        await self._db.execute(
            insert(SessionCost)
            .values(
                session_id=session.id,
                user_id=session.user_id,
                tier=tier,
                interrogation_seconds=seconds,
                # One runtime per room today. Phase 3 discovers whether a
                # three-voice panel is one agent session or three, which is the
                # number §4.3 says decides whether §4.4's margins hold.
                agent_session_count=1,
            )
            .on_conflict_do_update(
                index_elements=["session_id"],
                set_={
                    "tier": tier,
                    "interrogation_seconds": seconds,
                    "agent_session_count": 1,
                },
            )
        )

    async def _interrogation_seconds(self, session_id: uuid.UUID) -> int:
        """How long the metered window actually ran, summed over its spans.

        Summed rather than read off the first span: a session may open the
        interrogation phase more than once, and costing only the first would
        undercount exactly the sessions that were interrupted and resumed.
        """
        result = await self._db.execute(
            select(
                func.coalesce(
                    func.sum(
                        func.extract(
                            "epoch",
                            func.coalesce(SessionPhaseSpan.ended_at, func.now())
                            - SessionPhaseSpan.started_at,
                        )
                    ),
                    0,
                )
            ).where(
                SessionPhaseSpan.session_id == session_id,
                SessionPhaseSpan.phase == SessionPhase.INTERROGATION,
            )
        )
        return int(result.scalar_one())

    async def _tier(self, user_id: uuid.UUID) -> str:
        """Denormalised deliberately — see `SessionCost.tier`."""
        result = await self._db.execute(
            select(Account.entitlement_tier).where(Account.user_id == user_id)
        )
        return result.scalar_one()

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
