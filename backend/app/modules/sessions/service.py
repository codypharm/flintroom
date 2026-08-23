"""The session state machine.

Server-authoritative by design: the End button sends an *intent*, the server
decides. Nothing money-relevant is taken from the client.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from collections.abc import Sequence
from typing import NoReturn

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.archetypes import DEFAULT_PANEL, Archetype, by_name
from app.agents.difficulty import GENTLE
from app.agents.authored import is_authored
from app.agents.panel import assemble
from app.core.actors import ActorContext
from app.core.database import db_now
from app.core.errors import (
    AccountNotFound,
    DailyCeilingReached,
    FlintroomError,
    NoMinutesRemaining,
    ActiveSessionExists,
    InvalidStateTransition,
    SessionNotFound,
    SessionNotLive,
)
from app.core.logging import get_logger
from app.modules.audit_log.schemas import AuditEventType
from app.modules.audit_log.service import AuditService
from app.modules.billing.models import Account
from app.modules.billing.service import LedgerService
from app.modules.ingestion.service import confirm_ready
from app.modules.sessions.models import (
    Session,
    SessionMaterial,
    SessionPanelist,
    SessionPhaseSpan,
    TranscriptLine,
)
from app.modules.billing.models import Account
from app.modules.panels.authoring import AuthoringService
from app.modules.billing.tiers import (
    DAILY_SPEND_CEILING_USD,
    FREE_TIER,
    RECORDING_RETENTION_DAYS,
    SPEND_WINDOW,
)
from app.modules.voice.costs import SessionCost
from app.modules.sessions.models import SessionRecording
from app.modules.sessions.rehearsals import name_of, names_of
from app.modules.sessions.schemas import (
    SessionRead,
    RECENT_LIMIT,
    RecordingRead,
    RecordingState,
    GRACE_LIMIT,
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


def _distinct(material_ids: Sequence[uuid.UUID]) -> list[uuid.UUID]:
    """The same ids, deduplicated, in the order they were given.

    A client that names the same deck twice meant to attach it once, and the
    composite primary key would turn that into an `IntegrityError` — a 500 for
    what is at worst a clumsy request. Order is preserved because it is the
    order the user chose, and nothing downstream should have to guess at it.
    """
    seen: dict[uuid.UUID, None] = {}
    for material_id in material_ids:
        seen.setdefault(material_id, None)
    return list(seen)


async def room_still_standing_on(
    db: AsyncSession, *, material_id: uuid.UUID
) -> uuid.UUID | None:
    """The live session grounded in this material, if there is one.

    The mirror of `confirm_ready` going the other way: ingestion has to know
    whether a deck is under a running room before it destroys it, and the tables
    that answer that are this module's. Each module reads its own, and neither
    reaches across.

    A question rather than a refusal, unlike `confirm_ready`. What deleting a
    material may do is ingestion's rule to make, so this returns the fact and
    leaves the policy where the endpoint is.
    """
    return await db.scalar(
        select(Session.id)
        .join(SessionMaterial, SessionMaterial.session_id == Session.id)
        .where(
            SessionMaterial.material_id == material_id,
            Session.state.in_(LOCK_HOLDING_STATES),
        )
        .limit(1)
    )


class SessionService:
    """The only path through which session state changes."""

    def __init__(self, db: AsyncSession, actor: ActorContext | None = None) -> None:
        self._db = db
        self._actor = actor or ActorContext.system()
        # Built here rather than injected so that every session write is audited
        # under the same actor that performed it. A caller cannot hand in an
        # audit service attributing its writes to somebody else.
        self._audit = AuditService(db, self._actor, tag="sessions")

    async def start(
        self,
        *,
        user_id: uuid.UUID,
        material_ids: Sequence[uuid.UUID] = (),
        archetypes: Sequence[str] = (),
        repeats: uuid.UUID | None = None,
        rehearsal_name: str | None = None,
        audience: str | None = None,
    ) -> Session:
        """Open a session in `provisioning`, grounded in whatever it was handed.

        Bills nothing: the room has not opened yet. The first ledger entry comes
        from the first tick after the voice channel is established.

        Material is optional and the empty case is first-class, not degraded —
        `docs/auditor-grounding.md` gives the deckless panel plenty to attack,
        and a user who does not want to wait for extraction starts without a
        deck rather than being blocked.

        The set is fixed here and never afterwards. There is no attach endpoint
        on a running session on purpose: the Auditor's reference set must not
        move mid-interrogation, or the same spoken claim passes at minute two
        and fails at minute six, and *"why did the panel miss that"* stops
        having an answer.
        """
        attaching = _distinct(material_ids)

        # Both before the balance check and before the insert, so a room is never
        # opened that cannot be run. Ordering matters for what the user is told:
        # being refused for an unready deck or an unseatable panel is actionable,
        # while being told you are out of minutes and *then* that your deck is
        # not ready is two round trips for one attempt.
        #
        # The panel goes first because it is the cheaper question — one column on
        # the account against a join across materials — and because a room with
        # nobody in it is a more basic failure than a room with nothing to attack.
        chosen = list(archetypes) or [seat.name for seat in DEFAULT_PANEL]

        # Rows this account owns, resolved before the shipped library is
        # consulted. Scoped to the owner by `seatable`, so knowing another
        # account's panelist name is not enough to seat it — the name simply
        # does not resolve, and `assemble` refuses it exactly as it refuses a
        # typo. That is the honest answer to a caller with no business with it,
        # and it avoids a 403 confirming the row exists.
        #
        # Skipped entirely when nothing is asked for by name, which is the
        # common path: a default room is shipped archetypes and this would be a
        # query answering a question nobody posed.
        authored = (
            await AuthoringService(self._db).seatable(user_id=user_id, names=chosen)
            if any(is_authored(name) for name in chosen)
            else {}
        )

        panel = assemble(
            tier=await self._tier_of(user_id),
            chosen=chosen,
            authored=authored,
        )
        await confirm_ready(self._db, user_id=user_id, material_ids=attaching)

        if (existing := await self._active_session(user_id)) is not None:
            await self._deny_start(user_id, blocked_by=existing.id)

        # Rolled *before* the balance is judged, not after. The period reset is
        # lazy because the stack has no scheduler, so this read is what grants a
        # new month's allowance — checking first would tell a subscriber whose
        # month ticked over last night that they are out of minutes.
        balance = await LedgerService(
            self._db,
            # The request id is carried through rather than dropped: a period
            # reset triggered by a start belongs to the same request as the
            # start itself, and that is exactly the pair read back later.
            actor=ActorContext.user(user_id, request_id=self._actor.request_id),
        ).ensure_current_period(user_id=user_id)

        if balance.total_seconds <= 0:
            # The only moment the answer can be no. Product.md §4.5 forbids
            # interrupting a live interrogation for balance, so a room that
            # opens is a room that finishes.
            await self._deny_start(
                user_id,
                reason="no_minutes_remaining",
                error=NoMinutesRemaining(user_id=str(user_id)),
            )

        # Last of the refusals, and after the balance question on purpose. Out
        # of minutes is the user's own business and actionable — they can top
        # up; this is ours, and an account with no minutes cannot spend anything
        # anyway, so leading with it would send somebody the wrong way.
        await self._within_daily_ceiling(user_id)

        session = Session(
            user_id=user_id,
            state=SessionState.PROVISIONING,
            rehearsal_id=await self._rehearsal_of(user_id, repeats),
            # Stored on this room rather than pushed onto the lineage's root.
            # `rehearsals.py` reads the newest name in a group as the group's,
            # so naming a rehearsal on its fourth attempt names all four — and
            # nothing here has to update a row somebody else's request wrote.
            rehearsal_name=rehearsal_name,
            # Stored verbatim and never logged. #66: it is the presenter's own
            # prose about identifiable colleagues, and the composer is the only
            # thing that ever reads it — fenced, and only after `build_room`
            # hands it over.
            audience=audience,
        )
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

        for seat, archetype in enumerate(panel):
            # Same commit as the session, for the same reason as the material
            # below: a room whose seats landed in a later transaction could be
            # connected to before anybody was in it.
            self._db.add(
                SessionPanelist(
                    session_id=session.id, name=archetype.name, seat=seat
                )
            )

        for material_id in attaching:
            # Same commit as the session and its audit row. A room that exists
            # without its grounding is one the panel would interrogate blind,
            # and the user would have no way to tell which they got.
            self._db.add(
                SessionMaterial(session_id=session.id, material_id=material_id)
            )

        # Staged, not recorded: both rows belong to one commit, so a crash
        # cannot leave a session nobody can account for.
        self._audit.stage(
            AuditEventType.SESSION_STARTED,
            user_id=user_id,
            session_id=session.id,
            materials=len(attaching),
        )
        await self._db.commit()
        return session

    async def difficulty_of(self, *, session_id: uuid.UUID) -> int:
        """The rung this room should run at.

        **A room that repeats another runs at the pressure that rehearsal last
        ran at.** "Run it again" already restores the panel and the material; it
        did not restore the pressure, so the button handed back a different room
        than the one it named. The rung came from the account, and every debrief
        moves that — including debriefs of unrelated arguments, which is how a
        badly-handled demo day made somebody's board readout gentler.

        Two things broke. The same-rung comparison (`docs/rehearsals.md`
        decision 9) went silent exactly where it is wanted, and the rung drawn on
        each room in Progress became something the reader could not explain.

        **The account's rung is untouched and still means what
        `docs/difficulty-calibration.md` decision 3 says it means.** Resilience
        under pressure transfers between arguments, so it is what a *fresh*
        argument starts from and what calibration keeps moving. It is simply no
        longer what a repeat reads.

        **An explicit choice made after that attempt still wins.** Otherwise the
        pin is a trap: a rehearsal stuck at the gentle rung could never be made
        harder, and the one control the user has over pressure would do nothing
        on the screen where it matters most. `difficulty_chosen_at` is what makes
        that answerable — calibration and preference both write the same number,
        and only the timestamp says which one spoke last.

        Defaults to the gentle rung for an account that somehow has no row. That
        cannot happen on the session path, and if it ever did, the wrong answer
        to give a stranger is the hardest room we have.
        """
        session = await self._load(session_id)

        account = (
            await self._db.execute(
                select(Account.difficulty_level, Account.difficulty_chosen_at).where(
                    Account.user_id == session.user_id
                )
            )
        ).one_or_none()

        level = (account.difficulty_level if account else None) or GENTLE

        if session.rehearsal_id is None:
            return level

        # The newest attempt in this rehearsal that actually became a room.
        # `ran_at` writes on assembly, so a lineage of rooms that all failed to
        # provision has nothing to inherit and the account answers — which is
        # right, because there was no room to reproduce.
        pinned = (
            await self._db.execute(
                select(Session.difficulty_level, Session.started_at)
                .where(
                    Session.user_id == session.user_id,
                    func.coalesce(Session.rehearsal_id, Session.id)
                    == session.rehearsal,
                    Session.id != session.id,
                    Session.difficulty_level.is_not(None),
                )
                .order_by(Session.started_at.desc())
                .limit(1)
            )
        ).one_or_none()

        if pinned is None:
            return level

        chosen = account.difficulty_chosen_at if account else None
        if chosen is not None and chosen >= pinned.started_at:
            return level

        return pinned.difficulty_level

    async def ran_at(self, *, session_id: uuid.UUID, level: int) -> None:
        """Record the rung a room was assembled at.

        Idempotent by being a plain assignment: a socket that drops and
        reconnects rebuilds the room, and writing the same rung again is not an
        event. If the account's rung moved in between — the user changed it, or
        a debrief calibrated — the reconnected room genuinely is the new one and
        the record should say so.
        """
        await self._db.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(difficulty_level=level)
        )
        await self._db.commit()

    async def panel(self, *, session_id: uuid.UUID) -> tuple[Archetype, ...]:
        """Who is in this room, in the order they were seated.

        Resolved through `by_name` rather than returned as names, because every
        caller wants the archetype: the selection step reads personas, the
        composer reads one, and the client shows titles. Handing out strings
        would push the same lookup into three places.

        A name the library no longer answers to is **dropped, not raised**, and
        this is the one place in the panel code where that is right. Everywhere
        else a missing archetype means the user asked for something that does not
        exist, and refusing tells them so. Here it means a room was seated when
        the library was different — a live session mid-interrogation, or a
        settled one being read back for its debrief. Raising would take the room
        away from somebody sitting in it over a change they did not make.
        """
        rows = await self._db.execute(
            select(SessionPanelist.name)
            .where(SessionPanelist.session_id == session_id)
            .order_by(SessionPanelist.seat)
        )
        seated = [by_name(name) for name in rows.scalars()]

        if any(archetype is None for archetype in seated):
            # The only symptom otherwise is a room that is quietly smaller than
            # it was assembled to be, which reads as a broken panel.
            log.warning(
                "panel_seat_unresolved",
                session_id=str(session_id),
                seated=len(seated),
                resolved=sum(archetype is not None for archetype in seated),
            )

        return tuple(archetype for archetype in seated if archetype is not None)

    async def transcript(self, *, session_id: uuid.UUID) -> list[TranscriptLine]:
        """Every line of one room, in the order it happened.

        By `ordinal` rather than by `said_at`, and the difference is not
        cosmetic: lines are written as they are said, so two can share a clock
        reading, and `TranscriptLine.ordinal` exists precisely because "whatever
        order the rows come out" is not an order. The same lines rearranged
        describe a room that did not happen.

        Rows rather than a shaped read model. The debrief already reads these
        through `SessionTranscript` for grounding and the router needs them for a
        response; a second query shaped for one caller would be a second place
        for the ordering rule to be got wrong.
        """
        rows = await self._db.scalars(
            select(TranscriptLine)
            .where(TranscriptLine.session_id == session_id)
            .order_by(TranscriptLine.ordinal)
        )
        return list(rows)

    async def materials(self, *, session_id: uuid.UUID) -> list[uuid.UUID]:
        """What this room was grounded in, in the order it was attached.

        Ids rather than rows: the Auditor wants the claims behind them and the
        client wants to show what it attached, and neither is served by handing
        out a join table.
        """
        rows = await self._db.scalars(
            select(SessionMaterial.material_id)
            .where(SessionMaterial.session_id == session_id)
            .order_by(SessionMaterial.attached_at, SessionMaterial.material_id)
        )
        return list(rows)

    async def audience(self, *, session_id: uuid.UUID) -> str:
        """What the presenter said about the room they are facing, or "".

        #66. Read at room build rather than carried from start, for the reason
        `difficulty_of` is: this is the moment that decides the room somebody
        actually gets, and it is where `session_id` is already in hand.

        **Returns a string, never `None`.** The column is nullable because most
        rooms have no note, but the composer branches on truthiness and every
        caller downstream would otherwise have to remember the same `or ""`.
        One conversion at the one crossing; a missed one further in would fence
        the word None and hand it to a live room.
        """
        return (
            await self._db.scalar(
                select(Session.audience).where(Session.id == session_id)
            )
        ) or ""

    async def _within_daily_ceiling(self, user_id: uuid.UUID) -> None:
        """Refuse a room this account has already spent its day on.

        The circuit breaker `CLAUDE.md` names in its Metering Rules and nothing
        implemented until #73. `docs/voice-cost.md` leans on it explicitly: the
        abuse loop is bounded by the one-active-session rule to "on the order of
        a dollar an hour per account, against a daily spend ceiling that exists
        to catch exactly that" — and it did not exist.

        **Cost, not revenue.** A room under the meter's first tick charges the
        user nothing and must go on charging them nothing; what this bounds is
        what three providers can be made to charge *us* for rooms the meter will
        never bill.

        A per-account sum on the start path only. Never on the tick path, and
        never across users — `docs/deferred-scale-work.md` forbids a cross-user
        aggregate on the write path, and this keeps the property that a user
        contends only with themselves.

        `coalesce` on the column and on the sum. Every `session_costs` row
        written before pricing shipped has a null in it, and an empty window
        sums to null rather than zero — either would compare as "unknown" and
        fail open or closed depending on the operator, which is not a thing to
        leave to chance in a control that turns customers away.
        """
        spent = await self._db.scalar(
            select(
                func.coalesce(func.sum(func.coalesce(SessionCost.computed_cost_usd, 0)), 0)
            ).where(
                SessionCost.user_id == user_id,
                SessionCost.recorded_at >= await db_now(self._db) - SPEND_WINDOW,
            )
        )

        ceiling = DAILY_SPEND_CEILING_USD.get(
            await self._tier_of(user_id), DAILY_SPEND_CEILING_USD[FREE_TIER]
        )
        if spent is None or spent < ceiling:
            return

        # Logged as well as audited. The audit row proves it happened; this line
        # is what an operator greps when deciding whether the ceiling is set
        # right, which is a question the first heavy legitimate user will ask
        # for us.
        log.warning(
            "daily_ceiling_reached",
            user_id=str(user_id),
            spent_usd=str(spent),
            ceiling_usd=str(ceiling),
        )
        await self._deny_start(
            user_id,
            reason="daily_ceiling_reached",
            error=DailyCeilingReached(user_id=str(user_id)),
        )

    async def _deny_start(
        self,
        user_id: uuid.UUID,
        *,
        blocked_by: uuid.UUID | None = None,
        reason: str = "active_session_exists",
        error: FlintroomError | None = None,
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
        raise error or ActiveSessionExists(
            user_id=str(user_id),
            session_id=str(blocked_by) if blocked_by else None,
        )

    async def _rehearsal_of(
        self, user_id: uuid.UUID, repeats: uuid.UUID | None
    ) -> uuid.UUID | None:
        """The lineage a new room joins, or None for a fresh argument.

        **Read from the named room, never taken from the client.** A group id
        supplied directly would let a caller file their room into somebody
        else's lineage — or into one that does not exist — and Progress would
        then average two people's rehearsals together. What the client may say
        is *which room this repeats*, which is a claim code can check.

        Answered 404 rather than 403 for a room they do not own. As far as they
        are entitled to know it is not there, and a 403 is the difference
        between a guessed id and a real one.

        `coalesce` is the whole flattening rule: repeating a room that already
        belongs to a lineage joins *that* lineage rather than starting a chain
        below it, so A -> B -> C is one group and grouping stays a `GROUP BY`.
        """
        if repeats is None:
            return None

        found = await self._db.execute(
            select(func.coalesce(Session.rehearsal_id, Session.id)).where(
                Session.id == repeats, Session.user_id == user_id
            )
        )
        lineage = found.scalar_one_or_none()
        if lineage is None:
            raise SessionNotFound(session_id=str(repeats))

        return lineage

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

    async def recent(self, *, user_id: uuid.UUID) -> list[SessionRead]:
        """This account's rooms, newest first.

        **Scoped by a filter rather than by a check.** The single-session routes
        are guarded by `OwnedSession`, which has an id to compare — a list has
        none, so ownership has to be in the `WHERE` clause. Forgetting it there
        is not a 403 somebody sees, it is one account reading another's.

        Bounded rather than paged. `Product.md` §4.4 caps a Pro account at three
        hours a month, so a heavy user in their first year has a few dozen
        rooms, not thousands — and a limit is honest about that where an
        unbounded query would work until it did not. Paging is owed when the
        library surface exists and can express it.

        Returns `SessionRead`, so a room in a list and a room on its own are the
        same shape. Carries no transcript and no audio, per `CLAUDE.md`.
        """
        rows = await self._db.execute(
            select(Session)
            .where(Session.user_id == user_id)
            .order_by(Session.started_at.desc())
            .limit(RECENT_LIMIT)
        )

        # One query for every name in the account, rather than one per room.
        # A lineage's name lives on whichever of its rooms was given one, which
        # may be outside this window — so it cannot be resolved from the rows
        # above, and resolving it per row would be fifty round trips for a list.
        named = await names_of(self._db, user_id=user_id)

        rooms = list(rows.scalars())
        ours = [session.id for session in rooms]

        # **#94: these were missing, and their absence was silent.** `SessionRead`
        # defaults `archetypes` and `material_ids` to empty lists, so a list that
        # simply did not fill them in returned a plausible room that nobody sat
        # in and nothing grounded. Measured against the architect's dev database:
        # 62 sessions, 157 `session_panelists` rows, every session seated — and
        # every row in the Library reading as empty.
        #
        # It cost more than a wrong caption. "Run it again" re-seats from exactly
        # these two fields, so a re-run of a grounded, hand-picked room was
        # sending no panel and no deck, and the server filled the gap with the
        # shipped default.
        #
        # Batched rather than per row. `_read` pays two queries for one session
        # and says why that is the right trade there; the same shape here would
        # be a hundred round trips for a list of fifty.
        seated = await self._panels_of(ours)
        grounded = await self._materials_of(ours)

        return [
            SessionRead.model_validate(session).model_copy(
                update={
                    "recording": await self.recording(session_id=session.id),
                    "rehearsal_name": named.get(session.rehearsal),
                    "archetypes": seated.get(session.id, []),
                    "material_ids": grounded.get(session.id, []),
                }
            )
            for session in rooms
        ]

    async def _panels_of(
        self, session_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[str]]:
        """Who sat in each of these rooms, in seat order, in one query.

        Seat order is not presentation. `SessionStart.archetypes` carries order
        through rather than sorting it, `routing.choose` breaks a scoring tie on
        the panel's own index, and "Run it again" re-seats from this list — so a
        room rebuilt in a different order is a different room.
        """
        if not session_ids:
            return {}

        rows = await self._db.execute(
            select(SessionPanelist.session_id, SessionPanelist.name)
            .where(SessionPanelist.session_id.in_(session_ids))
            .order_by(SessionPanelist.session_id, SessionPanelist.seat)
        )

        seated: dict[uuid.UUID, list[str]] = {}
        for session_id, name in rows:
            seated.setdefault(session_id, []).append(name)
        return seated

    async def _materials_of(
        self, session_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        """What each of these rooms was grounded in, in attachment order."""
        if not session_ids:
            return {}

        rows = await self._db.execute(
            select(SessionMaterial.session_id, SessionMaterial.material_id)
            .where(SessionMaterial.session_id.in_(session_ids))
            .order_by(
                SessionMaterial.session_id,
                SessionMaterial.attached_at,
                SessionMaterial.material_id,
            )
        )

        grounded: dict[uuid.UUID, list[uuid.UUID]] = {}
        for session_id, material_id in rows:
            grounded.setdefault(session_id, []).append(material_id)
        return grounded

    async def rehearsal_name(self, *, session: Session) -> str | None:
        """What the lineage this room belongs to is called, or null.

        Takes the loaded row rather than an id, because both facts it needs —
        the owner and the group — are already on it, and re-reading them would
        be a query to find out what the caller is holding.
        """
        return await name_of(
            self._db, user_id=session.user_id, rehearsal=session.rehearsal
        )

    async def recording(self, *, session_id: uuid.UUID) -> RecordingRead:
        """Whether this room can still be heard, and until when.

        Answered from `session_recordings` rather than from the object store.
        The row outlives the audio deliberately — that is what lets an expired
        room be reported as *expired* rather than as one that was never
        recorded, and those are different sentences to the person reading them.
        Asking the store instead would collapse the two into "no object".

        The window is read from the owner's tier **now**, matching the retention
        sweep exactly. A user who upgrades sees the date on their old rooms move
        out, and one who downgrades sees it move in — there is one rule, applied
        in two places, rather than a stored expiry that would have to be
        rewritten on every tier change.
        """
        recording = await self._db.get(SessionRecording, session_id)
        if recording is None:
            return RecordingRead(state=RecordingState.NOT_RECORDED)
        if recording.deleted_at is not None:
            return RecordingRead(state=RecordingState.EXPIRED)

        session = await self._load(session_id)
        tier = await self._db.scalar(
            select(Account.entitlement_tier).where(Account.user_id == session.user_id)
        )
        days = RECORDING_RETENTION_DAYS.get(
            tier or FREE_TIER, RECORDING_RETENTION_DAYS[FREE_TIER]
        )
        # From `settled_at` when there is one, so the date a user is shown is
        # measured from the same mark the sweep uses. A room still running has
        # not started its window: it is playable and its expiry is not yet a
        # fact, so `stored_at` stands in until settlement makes it one.
        from_when = session.settled_at or recording.stored_at
        return RecordingRead(
            state=RecordingState.AVAILABLE,
            expires_at=from_when + timedelta(days=days),
        )

    async def record_progress(self, *, session_id: uuid.UUID) -> None:
        """The client is still there. Resets the reaper's clock, nothing else.

        Called by the voice layer, not by the client, and deliberately has no
        HTTP endpoint. The backend holds the streaming connection, so it
        already knows whether audio is flowing — and a mobile client cannot be
        force-updated, so a heartbeat endpoint published now would still be
        live years after the voice channel made it redundant. Until Phase 2
        lands there is no caller, and the session cap and idle timeout are what
        bound a forgotten room in the meantime.

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

    async def connection_opened(
        self, *, session_id: uuid.UUID, connection_id: uuid.UUID
    ) -> Session:
        """A socket now speaks for this room — first connect, resume, or
        supersede. One method for all three, so the matrix lives in one place.

        First connect is `activate` plus the nonce, in one commit. Resume
        clears the disconnect stamp and opens a fresh interrogation span —
        the new span is what re-arms billing and re-bases the idle clock, so
        the tunnel never enters either arithmetic. Supersede (a reconnect
        arriving before the old socket has died) records only the nonce: the
        span is still open because nothing ever closed it, and the stale
        socket's eventual `connection_lost` will be refused by the nonce it
        no longer holds. See docs/reconnect.md.
        """
        session = await self._load(session_id)
        if session.state is SessionState.PROVISIONING:
            # The `activate` path, with the nonce landing in the same commit —
            # a room whose state, span and speaker-of-record could disagree
            # would be three separate facts to keep honest.
            self._move(session, SessionState.ACTIVE)
            self._db.add(
                SessionPhaseSpan(
                    session_id=session.id, phase=SessionPhase.INTERROGATION
                )
            )
            log.info(
                "session_activated",
                user_id=str(session.user_id),
                session_id=str(session.id),
            )
        elif session.state is SessionState.ACTIVE:
            if session.disconnected_at is not None:
                session.disconnected_at = None
                self._db.add(
                    SessionPhaseSpan(
                        session_id=session.id, phase=SessionPhase.INTERROGATION
                    )
                )
                log.info(
                    "session_resumed",
                    user_id=str(session.user_id),
                    session_id=str(session.id),
                )
            else:
                log.info(
                    "connection_superseded",
                    user_id=str(session.user_id),
                    session_id=str(session.id),
                )
            session.last_progress_at = func.now()
        else:
            # Settled, finalizing, failed: there is no room here to speak for.
            self.require_transition(session, SessionState.ACTIVE)
        session.connection_id = connection_id
        await self._db.commit()
        return session

    async def connection_lost(
        self, *, session_id: uuid.UUID, connection_id: uuid.UUID
    ) -> None:
        """The socket that spoke for this room dropped without an ending.

        The room neither settles nor keeps billing: the disconnect stamp
        starts the reaper's reconnect window, and closing the interrogation
        span suspends the meter, the caps and the idle clock in the same
        write — the meter only sees rooms with an open span, and settlement
        sums spans, so the tunnel is unbilled by construction.

        Guarded by the nonce, deliberately: a half-open socket dies late, and
        by then its room may have been resumed by a newer connection. A stamp
        from the dead socket would stop that live room's billing and start a
        reaper clock under its presenter mid-answer, so anything but the
        current speaker is ignored. Quietly — the stale relay is doing
        nothing wrong; it is just no longer the one being listened to.
        """
        session = await self._load(session_id)
        if (
            session.state is not SessionState.ACTIVE
            or session.connection_id != connection_id
        ):
            log.info(
                "connection_lost_ignored",
                user_id=str(session.user_id),
                session_id=str(session.id),
                state=session.state.value,
            )
            return
        session.disconnected_at = func.now()
        await self._close_open_span(session_id)
        await self._db.commit()
        log.info(
            "room_waiting_for_reconnect",
            user_id=str(session.user_id),
            session_id=str(session.id),
        )

    async def enter_grace(self, *, session_id: uuid.UUID) -> bool:
        """A tick overdrafted. Start the grace clock, and say whether it has run out.

        One call rather than a stamp and a separate check, because the two are
        never useful apart: a caller that stamped grace and forgot to ask would
        be a room running past the cap for free, and one that asked without
        stamping would never reach the cap at all.
        """
        session = await self._load(session_id)
        self.require_live(session)
        if session.grace_started_at is None:
            session.grace_started_at = func.now()
            await self._db.commit()
            # The moment a user runs out mid-room. Not a money movement itself,
            # so it does not belong in the ledger — but it is the start of one,
            # since every second from here is written off at settlement. It is
            # also the signal behind "how often does this happen, and to whom",
            # which is the question §4.5's upgrade prompt turns on.
            log.info(
                "grace_started",
                user_id=str(session.user_id),
                session_id=str(session.id),
            )
            # A clock started this instant cannot have run out, and saying so
            # without asking the database keeps the common tick cheap.
            return False
        return await self._grace_expired(session_id)

    async def leave_grace(self, *, session_id: uuid.UUID) -> None:
        """A tick drew without overdrafting. Whatever grace was running is over.

        The counterpart to `enter_grace`, and called on the other branch of the
        same decision, so the tick loop either enters or leaves on every tick
        and cannot quietly do neither. Clearing rather than remembering is the
        decision recorded in docs Part 1: grace tracks the overdraft the session
        is in now, so a user who tops up and later runs dry gets a full window
        rather than the remainder of an old one.
        """
        session = await self._load(session_id)
        self.require_live(session)
        if session.grace_started_at is None:
            return
        session.grace_started_at = None
        await self._db.commit()

    @staticmethod
    def require_live(session: Session) -> None:
        """Refuse to act on a room that has stopped running.

        The meter selects live rooms and then acts on them, so a user pressing
        End or the reaper closing an orphan in between is ordinary traffic
        rather than a bug — which is why this is a business rule violation and
        not a crash. Public since the resume path: re-minting a stream ticket
        asks exactly this question about a room the caller owns.
        """
        if session.state is not SessionState.ACTIVE:
            raise SessionNotLive(
                session_id=str(session.id), state=session.state.value
            )

    async def _grace_expired(self, session_id: uuid.UUID) -> bool:
        """Has the grace clock passed the cap?

        Asked of Postgres rather than computed here, because the timestamp it is
        compared against was written by Postgres. Mixing in the worker's clock
        makes the cap depend on how far that worker has drifted — early, and a
        paying user is cut off mid-answer; late, and the write-off is unbounded
        by exactly the amount of the drift.
        """
        result = await self._db.execute(
            select(Session.grace_started_at < func.now() - GRACE_LIMIT).where(
                Session.id == session_id
            )
        )
        return bool(result.scalar_one())

    async def record_speech(self, *, session_id: uuid.UUID) -> None:
        """The user said something. Resets the idle clock, nothing else.

        Called by the voice layer, which is the only thing that can hear them.
        Deliberately separate from `record_progress`: that one means the client
        is still connected, and a phone streaming silence from an empty desk
        proves exactly that while being the case this has to catch.

        Not metered, not audited, and not a transition — a room with somebody
        talking in it is the ordinary state of the product, and recording it
        four times a minute into the audit trail would bury everything that
        actually needs proving.
        """
        session = await self._load(session_id)
        self.require_live(session)
        session.last_user_speech_at = func.now()
        await self._db.commit()

    async def settle(self, *, session_id: uuid.UUID) -> Session:
        """Billing is closed and the lock is released.

        `settled` means billing closed, not session closed: debrief and sparring
        are unmetered and remain available afterwards (Product.md §3.5, §4.1).
        """
        session = await self._load(session_id)
        self._move(session, SessionState.SETTLED)
        session.settled_at = await db_now(self._db)
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

        # Only ever closes another coaching span: billing is already closed
        # by the time this runs. An interrogation span is closed in exactly
        # two places — `begin_finalizing`, and `connection_lost` opening the
        # reconnect window — and this is deliberately neither of them.
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
        # Read once: closing two spans at two instants would be a lie about
        # what happened, and the second read is a round trip for nothing.
        closed_at = await db_now(self._db)
        for span in await self._open_spans(session_id):
            span.ended_at = closed_at

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

    async def _tier_of(self, user_id: uuid.UUID) -> str:
        """The caller's entitlement tier, which decides how many seats they get.

        A second read on the start path, and the only new cost this slice adds.
        Not folded into the balance read a few lines down: that one goes through
        `LedgerService` and rolls the entitlement period as a side effect, and
        borrowing its row to answer a different question would tie panel size to
        billing machinery it has nothing to do with.
        """
        tier = await self._db.scalar(
            select(Account.entitlement_tier).where(Account.user_id == user_id)
        )
        if tier is None:
            raise AccountNotFound(user_id=str(user_id))
        return tier

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
