import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.sessions.schemas import EndReason, SessionPhase, SessionState

#: A VARCHAR, deliberately not a native Postgres enum: `ALTER TYPE ... ADD
#: VALUE` cannot be reversed, which would make adding a sixth state a migration
#: hazard. `values_callable` stores the lowercase value rather than SQLAlchemy's
#: default of the member *name*.
#:
#: `create_constraint` is left off on purpose and the CHECK is declared by hand
#: below. SQLAlchemy would otherwise attach it through a DDL event listener,
#: where it exists in the database but not in the model's metadata — so Alembic
#: autogenerate sees a constraint it cannot account for and emits a
#: `drop_constraint` for it on the *next* unrelated migration. Declaring it
#: explicitly is what keeps the drift guard in tests/test_migrations.py honest.
session_state_column = Enum(
    SessionState,
    name="session_state",
    native_enum=False,
    length=16,
    values_callable=lambda enum: [member.value for member in enum],
)

end_reason_column = Enum(
    EndReason,
    name="session_end_reason",
    native_enum=False,
    length=24,
    values_callable=lambda enum: [member.value for member in enum],
)

phase_column = Enum(
    SessionPhase,
    name="session_phase",
    native_enum=False,
    length=16,
    values_callable=lambda enum: [member.value for member in enum],
)


def _sql_values(enum: type[Enum]) -> str:
    """Render an enum's values as a SQL list.

    Generated rather than hand-typed so that a new member cannot be added in
    Python while the database quietly keeps rejecting it.
    """
    return ", ".join(f"'{member.value}'" for member in enum)


class Session(Base):
    """One rehearsal, from panel spin-up through settlement.

    A single row spans the whole arc — interrogation, debrief, sparring — so
    that "which session was this" has one answer. What differs per phase lives
    in the append-only span table, not in extra session rows.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        # The state set, enforced by the database. A bug writing an unknown
        # state fails loudly at the write rather than quietly at the next read.
        CheckConstraint(
            f"state IN ({_sql_values(SessionState)})", name="ck_sessions_state"
        ),
        CheckConstraint(
            f"end_reason IS NULL OR end_reason IN ({_sql_values(EndReason)})",
            name="ck_sessions_end_reason",
        ),
        # Settled and timestamped are the same fact. Every cost and revenue
        # report keys off `settled_at`, so a settled session without one is
        # invisible to them while still counting as closed — and an unsettled
        # session *with* one is a closed session still holding the lock.
        CheckConstraint(
            "(state = 'settled') = (settled_at IS NOT NULL)",
            name="ck_sessions_settled_at",
        ),
        # One live session per user, enforced by Postgres rather than by a
        # check in the service. A service-level check cannot see an uncommitted
        # sibling transaction, so two devices tapping Start at the same moment
        # both pass it. Partial, because `settled` and `failed` sessions
        # accumulate forever and must not collide.
        Index(
            "uq_sessions_one_live_per_user",
            "user_id",
            unique=True,
            postgresql_where=text(
                "state IN ('provisioning', 'active', 'finalizing')"
            ),
        ),
        # The reaper's sweep. Partial over the same predicate as the lock index,
        # because settled and failed sessions accumulate for the life of the
        # account and are never reaped — indexing them would grow a hot index
        # forever to answer a question nobody asks about them.
        Index(
            "ix_sessions_reapable",
            "state",
            "last_progress_at",
            postgresql_where=text(
                "state IN ('provisioning', 'active', 'finalizing')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    #: Plain UUID, never a foreign key to `auth.users` — see CLAUDE.md
    #: → Database portability.
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)

    state: Mapped[SessionState] = mapped_column(session_state_column, nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    #: The last time this session did anything: a transition, or a billing tick.
    #: Distinct from `started_at`, which never moves — a twelve-minute
    #: interrogation is old but not stuck, and the reaper must not confuse the
    #: two. Written with the database's clock on every touch, because the reaper
    #: compares it against the database's clock and a skewed worker would
    #: otherwise throw users out of rehearsals they are still in.
    last_progress_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    #: When this session started running on a grace overdraft, or null if it is
    #: not. A timestamp on `active` rather than a sixth state (docs Part 2):
    #: nothing about ticking, idle detection or the reaper changes during grace,
    #: so a state would double the transition table for no behavioural
    #: difference. Nullable because it is cleared the moment a tick draws
    #: without overdrafting — grace measures the *current* overdraft, so a user
    #: who tops up mid-room gets a fresh window if they run dry again.
    grace_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: The last time the *user* said something, or null if they never have.
    #: Written by the voice layer, which is the only thing that can hear them.
    #: Panel speech deliberately does not touch this: an agent monologuing to an
    #: empty room is the expensive failure idle detection exists to catch, so
    #: treating it as activity would disarm the check in exactly that case.
    last_user_speech_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Why the session stopped. Null until it does.
    end_reason: Mapped[EndReason | None] = mapped_column(end_reason_column, nullable=True)

    #: Set exactly once, when billing closes. Null in every other state.
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionPhaseSpan(Base):
    """One stretch of one phase within a session. Append-only.

    Rows are inserted when a phase opens and closed once by setting `ended_at`;
    they are never deleted. That is what lets billing be reconstructed from the
    spans alone rather than trusted from a running total, and what gives §4.3
    the exact per-phase durations it needs to replace its guessed median
    coaching duration.
    """

    __tablename__ = "session_phase_spans"
    __table_args__ = (
        CheckConstraint(
            f"phase IN ({_sql_values(SessionPhase)})", name="ck_spans_phase"
        ),
        # A span cannot end before it began. Cheap here, and it is what lets any
        # duration query trust its own arithmetic instead of filtering for
        # nonsense rows.
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at", name="ck_spans_ordering"
        ),
        # One open span per session. Two would double-count the phase in §4.3's
        # per-phase durations, and for interrogation that is one stretch of
        # wall-clock time charged twice. Partial, because closed spans
        # accumulate for the life of the session and must not collide.
        Index(
            "uq_spans_one_open_per_session",
            "session_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    #: A real foreign key, unlike `user_id`: this points at a table we own, so
    #: it carries none of the portability cost the `auth.users` rule exists to
    #: avoid. Cascade because a span has no meaning without its session.
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    phase: Mapped[SessionPhase] = mapped_column(phase_column, nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    #: Null while the phase is open. For interrogation, null means the meter is
    #: running — which is why it is never inferred from the session's state.
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SessionMaterial(Base):
    """Which decks a room was grounded in.

    A join rather than a column on either side, because the relationship is
    genuinely many-to-many: `docs/ingestion.md` owns material by *account* so
    that a deck uploaded once can be rehearsed against five times, and one
    session can carry a deck plus a photograph of the whiteboard beside it.

    The set is fixed when the session starts and never changes afterwards. That
    is the whole point of the join existing at start rather than as an endpoint
    you call later: the Auditor's reference set must not move mid-session, or
    the same spoken claim passes at minute two and fails at minute six.
    """

    __tablename__ = "session_materials"
    __table_args__ = (
        # Every read is "what was this room grounded in", so the session leads.
        # Composite primary key rather than a surrogate id: the pair *is* the
        # fact, and it makes attaching the same deck twice impossible rather
        # than merely unlikely.
        PrimaryKeyConstraint("session_id", "material_id", name="pk_session_materials"),
        Index("ix_session_materials_material_id", "material_id"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Cascades too, and the consequence is deliberate: deleting a material
    #: erases the record that a past session used it. The claims cascade with it
    #: as well, so the grounding would be gone either way — a link pointing at a
    #: deck whose contents no longer exist is a citation that cannot be followed,
    #: which is worse than an honest absence.
    material_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("materials.id", ondelete="CASCADE"),
        nullable=False,
    )

    attached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SessionPanelist(Base):
    """One seat in one room, in the order it was assembled.

    **Names, not personas.** An archetype is configuration (`CLAUDE.md`), so what
    is stored is the key into `agents/archetypes.py` and the seat it took. The
    alternative — snapshotting persona and attack strategy per session — would
    freeze a room against the day its wording is improved, and every row would
    carry two kilobytes of text that is identical across every session ever run.

    The cost of that choice is real and worth naming: editing an archetype's
    persona changes how a *past* session reads if anything ever replays one. It
    is the right trade while archetypes are ours and few, and it is the decision
    to revisit when Pro users start authoring their own — at which point a
    panelist may point at a row rather than a constant, and the question becomes
    what happens when its author deletes it.

    Like `SessionMaterial`, the set is fixed when the session starts. A panel
    that could change mid-interrogation is a reference set moving under the
    Auditor: the archetype who owns a domain at minute two is not the one who
    owns it at minute six, and *"why did nobody challenge that"* stops having an
    answer.
    """

    __tablename__ = "session_panelists"
    __table_args__ = (
        # The pair *is* the fact, exactly as in `SessionMaterial` — and a
        # composite key makes seating the same archetype twice impossible rather
        # than merely refused. The service refuses it first, with a message; this
        # is what holds if a future caller forgets to.
        PrimaryKeyConstraint("session_id", "name", name="pk_session_panelists"),
        # One archetype per seat. Without it a bug writing two seat-0 rows
        # produces a room whose order depends on which row the planner returns
        # first — a panel that reassembles differently on different reads, which
        # would be invisible until a routing tiebreak went the other way.
        Index("uq_session_panelists_seat", "session_id", "seat", unique=True),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: The archetype's `name`, which is its identity everywhere else: in logs, in
    #: the transcript's speaker field, and in what the selection step answers.
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    #: Where this archetype sits, from zero. Persisted rather than derived from
    #: insertion order, because a room is read back by more than one caller and
    #: "whatever order the rows come out" is not an order.
    #:
    #: It is a real input, not presentation: `routing.choose` breaks a scoring
    #: tie on the panel's own index, so the seat a user gave an archetype decides
    #: who speaks when nothing else separates them.
    seat: Mapped[int] = mapped_column(SmallInteger, nullable=False)
