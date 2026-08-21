"""What one session cost us — the telemetry `Product.md` §4.3 requires.

Separate from `ledger_entries`, and deliberately. The ledger is what the *user*
owes and is the audited money record; this is what the *provider* charges us,
which is a different number, arrives later, and may disagree. Merging them would
make a reconciliation discrepancy indistinguishable from a billing bug — and the
ledger's reconciliation test guards a property this table must not be allowed to
disturb.

Every price in §4.4–4.5 rests on the unverified assumption that interrogation
costs ~$0.12/min because only one panelist speaks at a time. §4.3 names the
consequence plainly: if ElevenLabs bills per active agent session rather than
per synthesized minute, every tier margin collapses. `agent_session_count` is
the column that answers it.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SessionCost(Base):
    """One row per settled session. Never written for a room that never opened.

    Written at settlement rather than accumulated live, because settlement is
    where the interrogation window becomes final. A row maintained during the
    session would need correcting by every refund and grace write-off, and a
    figure that was true at some point mid-session is not one an invoice can be
    reconciled against.
    """

    __tablename__ = "session_costs"

    #: The daily spend ceiling's only question: what has this account cost us
    #: since a moment. `user_id` leads because it is the equality and
    #: `recorded_at` the range — reversed, the leading column would be useless
    #: for the lookup, and the ceiling runs on the session-start path where
    #: latency is the product.
    __table_args__ = (
        Index("ix_session_costs_user_recorded", "user_id", "recorded_at"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )

    #: Join keys, denormalised on purpose. Cost analysis groups by tier, and a
    #: user's tier changes — reading it live would re-price last quarter's
    #: sessions every time somebody upgraded.
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    tier: Mapped[str] = mapped_column(String(32), nullable=False)

    #: The metered window, counted from the interrogation span rather than from
    #: `sessions.started_at`. Spin-up is real latency but it is not
    #: interrogation, and cost has to be counted from the same mark as billing
    #: or the margin is measured against the wrong denominator.
    interrogation_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    #: The field §4.3 calls out as settling the load-bearing assumption:
    #: concurrent agent runtimes instantiated, not panelists heard. One today;
    #: Phase 3 discovers whether a three-voice panel is one runtime or three.
    agent_session_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    #: Reported by the provider adapter. Zero until the adapter can account for
    #: them — present now rather than added later so the first live sessions
    #: are measured by the same schema as the hundredth.
    tts_characters_synthesized: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    stt_seconds_processed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    llm_input_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    llm_output_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    auditor_invocations: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    #: The unmetered phases, which still cost money. §4.3 flags this as the
    #: model's largest uncontrolled exposure: the ~10-minute average behind the
    #: pricing is a guess, and if the real median runs past 20 minutes the soft
    #: cap needs tightening.
    debrief_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    sparring_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    #: Both kept. `computed_cost_usd` is ours, from observed usage;
    #: `provider_reported_cost` is theirs, pulled from the usage API where
    #: available. §4.3's acceptance criterion is that they agree within 10%,
    #: which is a comparison that needs both numbers side by side.
    computed_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    provider_reported_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
