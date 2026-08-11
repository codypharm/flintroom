import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditEvent(Base):
    """Append-only. Never updated, never deleted.

    Deliberately carries no foreign keys. An audit row must survive the deletion
    of whatever it describes — a record that disappears with the account it
    indicts is not an audit trail.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        # The two questions an operator actually asks: what happened to this
        # user, and what happened around this time.
        Index("ix_audit_events_user_occurred", "user_id", "occurred_at"),
        Index("ix_audit_events_occurred", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    actor: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: Nullable: some events (a rejected webhook with a bad signature) cannot be
    #: attributed to an account, and those are precisely the ones worth keeping.
    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
