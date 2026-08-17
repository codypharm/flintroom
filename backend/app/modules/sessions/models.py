import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
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


class TranscriptLine(Base):
    """One line of one room, whoever said it. Append-only.

    The first content Flintroom keeps. Everything else persisted so far is money
    (`ledger_entries`), proof (`audit_events`) or telemetry (`session_costs`) —
    none of it something a user would recognise as *theirs*. That is why
    `docs/session-retention.md` exists, and why retention lives on this table
    rather than being implied by it.

    Both sides, in one table. A schema that separated the panel's questions from
    the user's answers would make the natural read — the conversation — a union
    of two queries ordered by a column they would have to agree on, and would
    make "what did they say to the CFO's margin question" a join rather than two
    adjacent rows.

    Retained for the life of the account on every tier, including Free. Text is
    tens of KB and does not compound; only audio does, which is why the two have
    different windows and why that difference lives in `billing/tiers.py` rather
    than here.
    """

    __tablename__ = "session_transcript_lines"
    __table_args__ = (
        # The pair *is* the fact, as with `session_materials`: this line, at this
        # point in this room. A surrogate id would leave "the fourth thing said"
        # expressible twice, and a retry that wrote a line again would be a
        # duplicate rather than a no-op.
        PrimaryKeyConstraint("session_id", "ordinal", name="pk_session_transcript_lines"),
    )

    #: A real foreign key, unlike `user_id` — it points at a table we own, so it
    #: carries none of the portability cost the `auth.users` rule avoids. Cascade
    #: because a line has no meaning without its room, and deleting the session
    #: is how a transcript is disposed of.
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Where this line falls in the room, from zero. Explicit rather than
    #: inferred from a timestamp or an insert order: lines are written as they
    #: are said, so two could share a clock reading, and "whatever order the rows
    #: come out" is not an order — the same point `session_panelists.seat`
    #: already makes about seats.
    #:
    #: Order is content here, not presentation. `Product.md` §3.5 ranks weak
    #: *answers*, which is a judgement about a pair, and the same lines
    #: rearranged describe a room that did not happen.
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    #: `USER`, or an archetype's `name` — the same identity used in logs, in
    #: routing, and in the room's own in-memory transcript. Not a foreign key to
    #: `session_panelists`: a transcript is a record of what was said, and it
    #: must stay readable if the roster it was said by is ever reshaped.
    speaker: Mapped[str] = mapped_column(String(64), nullable=False)

    #: Unbounded, because an utterance is. `String(n)` here would mean a user who
    #: talked for ninety seconds without pausing lost the end of their own
    #: sentence — silently, and only sometimes.
    #:
    #: Never logged. `CLAUDE.md` forbids transcript text in logs and, unlike a
    #: secret, it cannot be caught by key-name redaction.
    text: Mapped[str] = mapped_column(Text, nullable=False)

    #: Whether this line opened by taking issue with the previous panelist's
    #: priorities — the turn shape #54 added.
    #:
    #: Persisted rather than derived, because it is not derivable. Once written,
    #: a disputing line and an ordinary one are the same text by the same kind of
    #: speaker in the same position; only the room knew the difference, and only
    #: at the moment it happened.
    #:
    #: `weakness.py` reads it to separate a question a colleague talked over from
    #: one the presenter ducked. Both are unanswered, one is the user's fault,
    #: and telling somebody they dodged a question that was taken away from them
    #: reads as the product not having listened.
    #: `"false"` rather than `text("false")`: `TranscriptLine.text` is a column
    #: on this class, so the SQLAlchemy import of the same name is shadowed
    #: inside this body.
    disputed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    #: What handed this speaker the floor — `finding`, `model` or `fallback`.
    #: Null for the user's own lines, which nobody chose.
    #:
    #: `chosen_by="finding"` is the only record that outlives the room of the
    #: Auditor having caught a contradiction: a `Finding` is read from one
    #: utterance, routes the next turn, and is discarded. The debrief ranks a
    #: contradiction above a panelist's dissatisfaction and needs to know which
    #: it is holding.
    #:
    #: Deliberately not an `Enum` column. `SelectedBy` is a routing vocabulary
    #: that may grow a fourth path, and a Postgres enum turns adding one into a
    #: migration that locks the table this room is actively writing to.
    #:
    #: Nullable rather than defaulted: a default of `"model"` would claim the
    #: selection model had spoken for every sentence the presenter said, and the
    #: room's health metric is a ratio over this column.
    chosen_by: Mapped[str | None] = mapped_column(String(16), nullable=True)

    said_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SessionRecording(Base):
    """That a room has audio, and whether it still does.

    A row per session rather than columns on `sessions`, following
    `session_costs`: the sessions row is on the hot path — it carries the
    one-live-per-user lock and the reaper's partial index — and widening it for
    a fact only two background jobs and one playback endpoint ever read would put
    that cost on every room, forever, for the benefit of none of them.

    Its real job is to make expiry *answerable*. The object key is deterministic,
    so audio could in principle be found without this — but "which rooms are past
    their window" is a question about owners, tiers and settlement times, and
    none of that is in a key. Without a row the only way to ask would be to list
    a bucket.
    """

    __tablename__ = "session_recordings"

    #: One recording per room, so the session *is* the identity. Cascade because
    #: a recording has no meaning without its session, and deleting the session
    #: is how an account's audio goes with it.
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )

    #: What was actually stored, after encoding. Kept for the storage
    #: projections in `docs/session-retention.md`, which are currently derived
    #: from one measured sine wave and should eventually be answered from real
    #: rooms — the same reason `session_costs` exists rather than trusting §4.4.
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)

    stored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    #: When the retention sweep removed the object, or null while it is still
    #: playable.
    #:
    #: The row survives the audio it describes, deliberately. It is the evidence
    #: that a published window was honoured — `docs/session-retention.md` chose
    #: an application sweep over a bucket lifecycle rule precisely because a
    #: rule leaves nothing to show anyone, and a row deleted alongside its object
    #: would leave exactly as little.
    #:
    #: It is also what makes the delete retryable: a store that refuses today is
    #: found again on the next pass, which is the shape `ingestion`'s material
    #: deletion already uses.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class UserPreference(Base):
    """What one account has chosen, where the choice is not money.

    Separate from `accounts` deliberately. That table is a cache over
    `ledger_entries` with an invariant — replaying the entries must reproduce it
    — and a consent flag has no such property. Putting one there would leave the
    row without a single reason to exist, and every future preference would land
    beside it by precedent.

    **A row is written only when somebody chooses something.** Every default
    lives in this class, not in a signup path, so an account that has never
    opened Settings has no row at all — which is also what makes adding the next
    preference a column with a default rather than a backfill.
    """

    __tablename__ = "user_preferences"

    #: Plain UUID, never a foreign key to `auth.users` — see CLAUDE.md
    #: → Database portability.
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)

    #: Whether interrogations are recorded for later playback.
    #:
    #: True by default, matching the disclosure: `docs/session-retention.md`
    #: chose on-by-default with a control, because most people never open
    #: Settings and an opt-in would build a compounding cost centre the majority
    #: never switch on — leaving "come back and play it" broken for almost
    #: everyone.
    #:
    #: Turning it off stops *new* rooms being recorded. It deliberately does not
    #: delete existing ones: those were made under a disclosure the user
    #: accepted, and silently destroying them on a toggle would be a surprise in
    #: the destructive direction. Deleting a room is its own explicit action.
    records_rooms: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
