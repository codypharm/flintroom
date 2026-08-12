"""The session state machine.

Server-authoritative by design: the End button sends an *intent*, the server
decides. Nothing money-relevant is taken from the client.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import NoReturn

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.errors import (
    ActiveSessionExists,
    InvalidStateTransition,
    SessionNotFound,
)
from app.core.logging import get_logger
from app.modules.audit_log.schemas import AuditEventType
from app.modules.audit_log.service import AuditService
from app.modules.sessions.models import Session, SessionPhaseSpan
from app.modules.sessions.schemas import (
    METERED_PHASES,
    EndReason,
    PhaseSpanRead,
    SessionPhase,
    SessionState,
)

#: The states that hold a user's one-session lock. Released at `settled` and
#: `failed` — neither costs anything to keep around.
LOCK_HOLDING_STATES = (
    SessionState.PROVISIONING,
    SessionState.ACTIVE,
    SessionState.FINALIZING,
)

#: The legal moves, declared in one place rather than as a precondition inside
#: each method. Two properties matter more than the convenience:
#:
#: - `settled` and `failed` are terminal, so no code path can reopen billing on
#:   a session that has already been settled and forgiven.
#: - `finalizing → finalizing` is legal *on purpose*. Settlement writes several
#:   ledger rows and can die halfway; the reaper must be able to retry it
#:   without the state machine treating the retry as an error.
TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    SessionState.PROVISIONING: frozenset({SessionState.ACTIVE, SessionState.FAILED}),
    SessionState.ACTIVE: frozenset({SessionState.FINALIZING}),
    SessionState.FINALIZING: frozenset({SessionState.FINALIZING, SessionState.SETTLED}),
    SessionState.SETTLED: frozenset(),
    SessionState.FAILED: frozenset(),
}

log = get_logger(__name__, tag="sessions")


class SessionService:
    """The only path through which session state changes."""

    def __init__(self, db: AsyncSession, actor: ActorContext | None = None) -> None:
        self._db = db
        self._actor = actor or ActorContext.system()
        # Built here rather than injected so that every session write is audited
        # under the same actor that performed it. A caller cannot hand in an
        # audit service attributing its writes to somebody else.
        self._audit = AuditService(db, self._actor, tag="sessions")

    async def start(self, *, user_id: uuid.UUID) -> Session:
        """Open a session in `provisioning`.

        Bills nothing: the room has not opened yet. The first ledger entry comes
        from the first tick after the voice channel is established.
        """
        if (existing := await self._active_session(user_id)) is not None:
            await self._deny_start(user_id, blocked_by=existing.id)

        session = Session(user_id=user_id, state=SessionState.PROVISIONING)
        self._db.add(session)
        try:
            # Flush, not commit. The insert has to reach the database so the row
            # takes its id and the unique index can reject a racer, but the
            # transaction stays open so the audit row joins the same commit.
            await self._db.flush()
        except IntegrityError as exc:
            # A racer committed between our check and our insert. The database
            # is the arbiter, and losing the race is an ordinary product outcome
            # — the user has a session, just not this one. Never a 500.
            await self._db.rollback()
            if not self._is_one_live_session_violation(exc):
                raise
            await self._deny_start(user_id, reason="lost_start_race")

        # Staged, not recorded: both rows belong to one commit, so a crash
        # cannot leave a session nobody can account for.
        self._audit.stage(
            AuditEventType.SESSION_STARTED, user_id=user_id, session_id=session.id
        )
        await self._db.commit()
        return session

    async def _deny_start(
        self,
        user_id: uuid.UUID,
        *,
        blocked_by: uuid.UUID | None = None,
        reason: str = "active_session_exists",
    ) -> NoReturn:
        """Refuse a start and leave evidence that it happened.

        A denial changes nothing, so without this the only record that a user
        was repeatedly refused is an application log line that may have been
        sampled away. CLAUDE.md requires denials to be recorded.
        """
        await self._audit.record(
            AuditEventType.SESSION_START_DENIED,
            user_id=user_id,
            session_id=blocked_by,
            reason=reason,
        )
        raise ActiveSessionExists(
            user_id=str(user_id),
            session_id=str(blocked_by) if blocked_by else None,
        )

    async def activate(self, *, session_id: uuid.UUID) -> Session:
        """The voice channel is up. From here the meter runs."""
        session = await self._load(session_id)
        self._move(session, SessionState.ACTIVE)
        # The state change and the span open together. A session that is
        # `active` with no open interrogation span would be running a room the
        # ledger has no billable window to attach to.
        self._db.add(
            SessionPhaseSpan(session_id=session.id, phase=SessionPhase.INTERROGATION)
        )
        await self._db.commit()

        log.info(
            "session_activated", user_id=str(session.user_id), session_id=str(session.id)
        )
        return session

    async def fail(
        self,
        *,
        session_id: uuid.UUID,
        end_reason: EndReason = EndReason.PROVISIONING_FAILED,
    ) -> Session:
        """Agent spin-up died before any audio existed.

        Terminal, and deliberately not routed through `finalizing`: nothing was
        billed, so there is nothing to settle. `settled_at` stays null, which is
        what keeps a room that never opened out of the cost reports.
        """
        session = await self._load(session_id)
        self._move(session, SessionState.FAILED)
        session.end_reason = end_reason
        await self._db.commit()

        log.warning(
            "session_failed",
            user_id=str(session.user_id),
            session_id=str(session.id),
            end_reason=end_reason.value,
        )
        return session

    async def begin_finalizing(
        self, *, session_id: uuid.UUID, end_reason: EndReason
    ) -> Session:
        """Stop the meter and start settling.

        Separate from `settle` because settlement writes several ledger rows and
        can die partway through. Recording the intent first is what lets the
        reaper distinguish "finished settling" from "died halfway."
        """
        session = await self._load(session_id)
        self._move(session, SessionState.FINALIZING)
        session.end_reason = end_reason
        # Stopping the meter and closing the billable window are one event. Two
        # separate steps would eventually be half-performed, and a span left
        # open bills forever on every replay of the ledger.
        await self._close_open_span(session_id)
        await self._db.commit()

        log.info(
            "session_finalizing",
            user_id=str(session.user_id),
            session_id=str(session.id),
            end_reason=end_reason.value,
        )
        return session

    async def record_progress(self, *, session_id: uuid.UUID) -> None:
        """The client is still there. Resets the reaper's clock, nothing else.

        Called by the billing tick, which doubles as the heartbeat — one
        mechanism rather than two, so a session cannot be paying for a room it
        has stopped proving anyone is in. Deliberately not part of
        `charge_tick`: the ledger has no business writing to a session row, and
        keeping the two calls in the tick loop is what makes "we billed but did
        not hear from the client" a state the reaper can still see.
        """
        session = await self._load(session_id)
        session.last_progress_at = func.now()
        await self._db.commit()

    async def settle(self, *, session_id: uuid.UUID) -> Session:
        """Billing is closed and the lock is released.

        `settled` means billing closed, not session closed: debrief and sparring
        are unmetered and remain available afterwards (Product.md §3.5, §4.1).
        """
        session = await self._load(session_id)
        self._move(session, SessionState.SETTLED)
        session.settled_at = datetime.now(UTC)
        self._audit.stage(
            AuditEventType.SESSION_SETTLED,
            user_id=session.user_id,
            session_id=session.id,
            end_reason=session.end_reason.value if session.end_reason else None,
        )
        await self._db.commit()
        return session

    async def open_phase(
        self, *, session_id: uuid.UUID, phase: SessionPhase
    ) -> PhaseSpanRead:
        """Begin an unmetered coaching phase.

        Only the coaching phases. Interrogation spans are opened by `activate`
        alone, so there is no call anywhere in the codebase that can start the
        meter without going through the state machine — see the refusal in
        `_reject_metered_phase`.
        """
        session = await self._load(session_id)
        self._reject_metered_phase(session, phase)
        self._require_billing_closed(session, phase)

        # Only ever closes another coaching span: billing is already closed by
        # the time this runs, so `begin_finalizing` remains the only thing in
        # the codebase that can close an interrogation span.
        await self._close_open_span(session_id)
        # Read before the rollback below can expire it. A rollback expires every
        # object in the session even with `expire_on_commit` off, and touching
        # an expired attribute afterwards triggers a lazy refresh — blocking IO
        # inside an async call, surfacing as MissingGreenlet rather than as
        # anything resembling the real cause.
        user_id = session.user_id

        span = SessionPhaseSpan(session_id=session.id, phase=phase)
        self._db.add(span)
        try:
            await self._db.commit()
        except IntegrityError as exc:
            # A second device opened the same phase first. Unlike a start race
            # this is not a denial: nothing is billed either way and both
            # devices wanted the user in the same phase, so handing back the
            # span that won is the honest outcome. A 409 here would refuse a
            # free feature to protect nothing.
            await self._db.rollback()
            if not self._is_one_open_span_violation(exc):
                raise
            log.info(
                "phase_open_lost_race",
                user_id=str(user_id),
                session_id=str(session_id),
                phase=phase.value,
            )
            return await self._open_span(session_id)

        log.info(
            "phase_opened",
            user_id=str(user_id),
            session_id=str(session_id),
            phase=phase.value,
        )
        return PhaseSpanRead.model_validate(span)

    @staticmethod
    def _reject_metered_phase(session: Session, phase: SessionPhase) -> None:
        """Refuse to open a billable phase through the coaching door.

        The metering boundary is a trust mechanic, not a tuning knob (CLAUDE.md
        → Metering Rules), so it is enforced where it cannot be routed around
        rather than by every caller remembering which phases cost money. A
        settled session is billing-closed; opening interrogation on one would
        restart the meter on a session already paid for and forgiven.
        """
        if phase in METERED_PHASES:
            raise InvalidStateTransition(
                session_id=str(session.id),
                from_state=session.state.value,
                to_state=phase.value,
            )

    @staticmethod
    def _require_billing_closed(session: Session, phase: SessionPhase) -> None:
        """Coaching opens after settlement, never during the room.

        Opening a phase closes whatever span is open, so permitting this while
        the session is `active` would stop the meter through a door that has no
        business touching billing — and leave a session still `active`, still
        holding the lock, with no span for the next tick to attach to. §4.1 puts
        settlement first: the panel finishes, the session settles, then debrief.
        """
        if session.state is not SessionState.SETTLED:
            raise InvalidStateTransition(
                session_id=str(session.id),
                from_state=session.state.value,
                to_state=phase.value,
            )

    async def _close_open_span(self, session_id: uuid.UUID) -> None:
        """Close whichever phase is currently open, if any.

        Tolerant of there being none: the reaper retries `finalizing`, and a
        retry that found nothing left to close is a success, not an error.
        """
        for span in await self._open_spans(session_id):
            span.ended_at = datetime.now(UTC)

    async def _open_span(self, session_id: uuid.UUID) -> PhaseSpanRead:
        """The phase currently open. Only called where one must exist."""
        [span] = await self._open_spans(session_id)
        return PhaseSpanRead.model_validate(span)

    async def _open_spans(self, session_id: uuid.UUID) -> list[SessionPhaseSpan]:
        result = await self._db.execute(
            select(SessionPhaseSpan)
            .where(
                SessionPhaseSpan.session_id == session_id,
                SessionPhaseSpan.ended_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        return list(result.scalars())

    @staticmethod
    def _is_one_open_span_violation(exc: IntegrityError) -> bool:
        """Checked by name, for the reason given on the start-race check: any
        other constraint failing must stay a 500 rather than be reported back as
        a benign duplicate."""
        return "uq_spans_one_open_per_session" in str(getattr(exc, "orig", exc))

    async def get(self, *, session_id: uuid.UUID) -> Session:
        """Read one session, or 404. The only public read of a session row."""
        return await self._load(session_id)

    async def spans(self, *, session_id: uuid.UUID) -> list[PhaseSpanRead]:
        """Every phase this session has been through, oldest first.

        Chronological rather than newest-first: a span list is read as a
        timeline of what happened, not as an incident log read backwards.
        """
        result = await self._db.execute(
            select(SessionPhaseSpan)
            .where(SessionPhaseSpan.session_id == session_id)
            .order_by(SessionPhaseSpan.started_at, SessionPhaseSpan.id)
        )
        return [PhaseSpanRead.model_validate(row) for row in result.scalars()]

    @staticmethod
    def require_transition(session: Session, to_state: SessionState) -> None:
        """Refuse a transition that the table does not allow, changing nothing.

        Public so that a caller doing work *around* a transition can check the
        precondition before that work rather than after it. Settlement needs
        exactly this: it writes money and then closes the session, and a close
        rejected at the end leaves the money already committed against a session
        that is still running.

        Refusing is a business rule violation (422), not a crash: a duplicate
        End tap or a reaper racing a user is ordinary traffic, not a bug.
        """
        if to_state not in TRANSITIONS[session.state]:
            raise InvalidStateTransition(
                session_id=str(session.id),
                from_state=session.state.value,
                to_state=to_state.value,
            )

    @classmethod
    def _move(cls, session: Session, to_state: SessionState) -> None:
        """Apply a transition, or refuse it.

        Every transition is progress, so the reaper's clock is reset here rather
        than in each method — one place to keep honest as states are added, and
        no way to add a transition that silently leaves a session looking stuck.

        `func.now()` rather than a Python timestamp so the value is written by
        the same clock the reaper compares it against. The attribute holds a SQL
        expression until the row is next read, which is why nothing in-process
        reads it back.
        """
        cls.require_transition(session, to_state)
        session.state = to_state
        session.last_progress_at = func.now()

    async def _load(self, session_id: uuid.UUID) -> Session:
        result = await self._db.execute(
            select(Session)
            .where(Session.id == session_id)
            .execution_options(populate_existing=True)
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise SessionNotFound(session_id=str(session_id))
        return session

    @staticmethod
    def _is_one_live_session_violation(exc: IntegrityError) -> bool:
        """Only the one-live-session index means "you already have a session".

        Checked by name so that some other constraint failing is not silently
        reported to the user as a duplicate session — that would turn a real bug
        into a plausible-looking 409 and hide it.
        """
        return "uq_sessions_one_live_per_user" in str(getattr(exc, "orig", exc))

    async def _active_session(self, user_id: uuid.UUID) -> Session | None:
        """The session currently holding this user's lock, if any.

        `settled` and `failed` are deliberately excluded: a user sitting in
        yesterday's debrief is not blocked from starting a fresh interrogation,
        because debrief is unmetered and holds no resources.
        """
        result = await self._db.execute(
            select(Session)
            .where(Session.user_id == user_id, Session.state.in_(LOCK_HOLDING_STATES))
            .limit(1)
        )
        return result.scalar_one_or_none()
