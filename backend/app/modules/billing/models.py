import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.agents.difficulty import GENTLE
from app.core.database import Base


class Account(Base):
    """Cached per-bucket balance for one user.

    The balance is a cache over `ledger_entries`, kept because the session-start
    path reads it and must stay O(1). Replaying the entries must always reproduce
    it; where they disagree, the entries are right and the cache is the bug.
    """

    __tablename__ = "accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    entitlement_tier: Mapped[str] = mapped_column(String(32), nullable=False)

    #: Monotonic counter, not a calendar key. It advances once per elapsed
    #: entitlement period and makes the allowance grant idempotent by
    #: construction: the key is derived from it, so a re-grant cannot insert.
    #: When somebody asked for this account to be deleted, or null.
    #:
    #: A timestamp on the account rather than a state, for the reason
    #: `grace_started_at` is one on a session: nothing about how the account
    #: behaves changes during the window — the balance is still the balance and
    #: the sweeps still sweep — so a state would double the table for no
    #: behavioural difference.
    #:
    #: Null again once cancelled, which is what makes signing in able to call it
    #: off (`docs/account-deletion.md` decision 5). Set once and never advanced:
    #: a second request must not push the purge back another seven days, or the
    #: deletion recedes from the person who asked for it.
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    #: When the purge actually ran, or null.
    #:
    #: Two timestamps rather than clearing the first, because they answer
    #: different questions: when somebody asked, and when it happened. The
    #: request stays true after the purge, and the sweep needs to tell an
    #: account it has already emptied from one whose window has just closed —
    #: without that it would re-purge every pass, writing an audit row each time
    #: and making the swept count useless as an alerting signal.
    #:
    #: **The row itself survives**, and that is the anonymisation working rather
    #: than a leftover. `accounts` holds tier, period and three balances and
    #: nothing identifying; once `auth_identities` is destroyed the `user_id` is
    #: an opaque key, and the ledger and cost telemetry keep pointing at it.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: How hard the room pushes this person — #55's rung, 1 to 3.
    #:
    #: On `accounts` rather than in a table of its own because it is one number
    #: per user with no history worth keeping, exactly like the tier beside it.
    #: The rungs and what they mean live in `agents/difficulty.py`; this column
    #: knows only that it is a small integer.
    #:
    #: **Defaults to the gentle rung**, which is how a first session gets one
    #: without a lookup or a first-run branch. `docs/difficulty-calibration.md`
    #: decision 4: a first room that destroys somebody produces churn rather
    #: than resilience, and the case is far too common to leave to a special
    #: case that could be wrong silently.
    #:
    #: Read through `difficulty.pressure_at`, never directly. That call clamps,
    #: so a row holding 7 produces a real room rather than ending a metered
    #: session over bookkeeping.
    difficulty_level: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=GENTLE, server_default=str(GENTLE)
    )

    #: When the user last set the rung themselves, or null if they never have.
    #:
    #: **The only thing that separates a preference from a calibration.** Both
    #: write `difficulty_level`, and once written the two are indistinguishable
    #: — which matters because a room that repeats another opens at the rung
    #: that rehearsal last ran at, and the setup screen's control has to be able
    #: to beat that pin. Without a timestamp there is no way to ask "did they
    #: say this *after* that attempt", and the control would silently do nothing
    #: on the one screen where it matters most.
    #:
    #: Set by `PanelService.choose` and by nothing else. `calibrate` deliberately
    #: leaves it alone: the machine moving the number is not the user asking.
    difficulty_chosen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    period_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    period_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    balance_allowance_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    balance_free_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    balance_topup_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class LedgerEntry(Base):
    """Append-only. Never updated, never deleted.

    A correction is a new entry with the opposite sign, so the history stays
    replayable and the audit trail stays honest about what happened.
    """

    __tablename__ = "ledger_entries"
    __table_args__ = (
        # The idempotency check runs on every tick of every live session. Without
        # this it is a sequential scan of the entire ledger, and the ledger only
        # ever grows.
        Index("ix_ledger_entries_session_tick", "session_id", "tick_index"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.user_id"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    #: Set on tick entries only. One tick can produce several entries when it
    #: straddles buckets, so the tick — not the entry — is the unit of replay.
    tick_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    bucket: Mapped[str] = mapped_column(String(16), nullable=False)
    delta_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)

    #: Provenance. A delta and a reason say what moved; these say who moved it.
    actor: Mapped[str] = mapped_column(String(16), nullable=False, server_default="system")
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: Total across all buckets immediately after this entry. Denormalised so an
    #: admin view shows a running balance without replaying the log per row.
    balance_after_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
