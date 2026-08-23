import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AppEvent(Base):
    """One thing the app reported happening — first-party analytics, #105.

    **A name, a user and a time, and deliberately nothing else.** There is no
    properties column: a JSON blob on an analytics row is where transcript
    text would eventually leak into a table with a twelve-month lifetime, and
    every funnel fact this product needs — rooms started, debriefs opened,
    sparring used, purchases — already lives in the domain tables that own
    those acts. What they cannot answer is whether a person *came back*,
    which is the question `app_open` exists for. A property earns a column
    (and a migration, and a privacy-policy sentence) when a question needs
    it, not before.

    Rows die twice over: with the account (`billing/deletion.py` purges by
    `user_id` — this table is in `PURGED`, and the completeness tests refuse
    a table that carries a `user_id` without a deletion decision) and at
    twelve months (`AnalyticsService.sweep`, riding the same loop as every
    other retention promise).
    """

    __tablename__ = "app_events"
    __table_args__ = (
        # The one query this table exists for: this account's events in a
        # window — retention curves, DAU, "did they come back". Leading with
        # `user_id` because it is the equality and `at` the range, the same
        # reasoning `session_costs` records for its own index.
        Index("ix_app_events_user_at", "user_id", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    #: Plain UUID, never a foreign key to `auth.users` — see CLAUDE.md
    #: → Database portability.
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    #: A slug from the client's vocabulary, shaped like `app_open` or
    #: `settings.viewed`. The pattern lives on the request schema and is the
    #: whole defence against this column holding prose.
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    #: The server's clock, never the client's. A phone's clock lies — time
    #: zones, manual settings, batching across a backgrounded app — and every
    #: retention question this table answers is asked in one timeline.
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
