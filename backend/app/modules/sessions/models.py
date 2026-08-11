import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.sessions.schemas import SessionState

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

#: Rendered from the enum rather than hand-typed, so a new state cannot be added
#: to the Python enum while the database quietly keeps rejecting it.
_STATE_VALUES = ", ".join(f"'{member.value}'" for member in SessionState)


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
        CheckConstraint(f"state IN ({_STATE_VALUES})", name="ck_sessions_state"),
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

    #: Set exactly once, when billing closes. Null in every other state.
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
