from enum import Enum

from pydantic import BaseModel, ConfigDict


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


class LedgerEntryRead(BaseModel):
    """One immutable line of the audit trail."""

    model_config = ConfigDict(from_attributes=True)

    bucket: Bucket
    delta_seconds: int
    reason: EntryReason
