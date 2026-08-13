from enum import Enum

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.actors import Actor


class Bucket(str, Enum):
    """Where a second of interrogation time is drawn from.

    Spend order is fixed by Product.md §4.5 and lives in the service, not here:
    allowance first (it expires), then free, then top-up (the user paid for it
    and it never expires).
    """

    ALLOWANCE = "allowance"
    FREE = "free"
    TOPUP = "topup"


class EntryReason(str, Enum):
    """Why a ledger entry exists. Every entry is typed; none are anonymous."""

    GRANT_ALLOWANCE = "grant_allowance"
    GRANT_FREE = "grant_free"
    GRANT_TOPUP = "grant_topup"
    EXPIRE_ALLOWANCE = "expire_allowance"
    TICK = "tick"
    REFUND_IDLE = "refund_idle"
    REFUND_PROVIDER_FAILURE = "refund_provider_failure"
    GRACE_FORGIVEN = "grace_forgiven"


class Balance(BaseModel):
    """A read of the cached balance, per bucket."""

    model_config = ConfigDict(from_attributes=True)

    allowance_seconds: int
    free_seconds: int
    topup_seconds: int

    @property
    def total_seconds(self) -> int:
        return self.allowance_seconds + self.free_seconds + self.topup_seconds

    @property
    def remaining_minutes(self) -> int:
        """Whole minutes remaining, floored.

        Seconds are charged exactly; the displayed figure floors, so the user
        always holds slightly more than shown rather than slightly less.

        Clamped at zero: a grace overdraft is real in the ledger but must never
        be shown as a debt, and it is forgiven at settlement regardless.
        """
        return max(self.total_seconds, 0) // 60

    @property
    def has_time_remaining(self) -> bool:
        """Whether any time is left at all, however little.

        Separate from `remaining_minutes` because 59 seconds and 0 seconds both
        floor to zero minutes and only one of them can start a session. Exposing
        this keeps the raw seconds out of the interface, which §4.6 requires —
        a second-by-second figure is the depleting counter by another name.
        """
        return self.total_seconds > 0


class BalanceRead(BaseModel):
    """What a client is told about its own balance.

    Two fields, and the omissions are the point. No seconds: §4.6 forbids a
    depleting counter, and raw seconds on the wire is that counter with the
    rounding left to whoever wrote the client — one of them will round up and
    promise a minute that is not there.

    No per-bucket breakdown either. Which bucket a second comes from is spend
    ordering, an internal rule, and showing three numbers that deplete in turn
    is the credits display §4.6 exists to refuse.
    """

    model_config = ConfigDict(from_attributes=True)

    remaining_minutes: int
    has_time_remaining: bool


class LedgerEntryRead(BaseModel):
    """One immutable line of the audit trail."""

    model_config = ConfigDict(from_attributes=True)

    bucket: Bucket
    delta_seconds: int
    reason: EntryReason

    actor: Actor
    actor_id: str | None = None
    request_id: str | None = None
    balance_after_seconds: int = 0
    created_at: datetime | None = None
