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
    #: The room billed interrogation time but processed zero STT seconds — it
    #: never heard the presenter at all. A technical failure by CLAUDE.md's own
    #: rule, whatever the recorded end reason. See docs/reconnect.md.
    REFUND_UNHEARD = "refund_unheard"
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


class PlanRead(BaseModel):
    """One rung, described by what it gets you — never by what it costs.

    **The price is deliberately absent, and that is the whole seam.** What
    somebody is charged is the store's: in their currency, after whatever
    regional adjustment applies, and changeable in a console without a release.
    What they *get* is ours, and every field here already existed in `tiers.py`
    before this schema did.

    Published rather than shipped in the app, on the argument
    `/v1/materials/limits` already made: *"this exists so the tier table has one
    home rather than a second copy shipped in an app release."* A client holding
    its own ladder can offer a plan we retired.
    """

    model_config = ConfigDict(from_attributes=True)

    #: The tier key — `free`, `starter`, `pro`. What `entitlement_tier` holds.
    name: str

    #: What to call it on screen.
    title: str

    #: Whole minutes of interrogation. §4.6 forbids a depleting counter and asks
    #: for "the largest honest unit", so this is minutes and the client says
    #: "3 hours" where that reads better — the figure stays exact either way.
    minutes: int

    #: Whether those minutes come back each month.
    #:
    #: **The free tier's do not**, and the difference is the whole of what that
    #: tier is. A card reading "15 minutes" beside "90 minutes a month" would be
    #: read as a smaller monthly allowance — a more generous plan than the one
    #: that exists, and a promise the ledger would refuse to keep.
    renews: bool

    #: How many panelists may be seated.
    seats: int

    #: How long a saved room stays playable, per `docs/session-retention.md`.
    retention_days: int

    #: The largest file this tier may attach, in whole megabytes.
    max_upload_mb: int

    #: Whether this tier may write its own archetype (#65).
    may_author: bool

    #: Always true, and on every plan rather than stated once.
    #:
    #: §4.4: *"All tiers include unmetered debrief and sparring."* §4.6: *"Say
    #: what is unlimited, prominently... at the top of every tier card, not in a
    #: footnote."* A client that had to remember to add it is one that will
    #: forget on a card.
    unmetered_coaching: bool = True

    #: Whether the caller is on this plan already.
    #:
    #: Answered here rather than left to the client to compare against a tier
    #: string, because the client would then need its own map of what
    #: `pro_annual` and `teams` fall onto — the second table this endpoint
    #: exists to prevent. Nothing is marked for a tier off the ladder, which is
    #: honest: none of the rungs listed is the plan they hold.
    current: bool = False


class PackRead(BaseModel):
    """One top-up, by what it grants — never by what it costs.

    §4.5's packs, published for the same reason `PlanRead` is: the minutes are
    ours and the price is the store's, so a screen can describe a pack before
    any offering exists.
    """

    model_config = ConfigDict(from_attributes=True)

    #: Our key for it, and what a store product declares to say which pack it
    #: sells. Not the store's product identifier — that belongs to the console.
    name: str

    #: What it is called. Ours, because the store's title is a marketing string
    #: and these names carry the occasion each pack is for.
    title: str

    #: Whole minutes granted.
    minutes: int


class PurchaseOptions(BaseModel):
    """Which control leads on the buy screen, and what there is to lead with.

    §4.5's Credit-Toward-Upgrade Rule, answered on the server. The window and
    the threshold are business rules, and a client computing them from a raw
    count would be a second implementation free to drift from this one.

    **A decision, not a tally.** The count of top-ups is deliberately not on the
    wire. `BalanceRead` above refuses raw seconds for the same reason §4.6 gives
    — a number that only goes one way invites a display that makes people
    ration — and "you have topped up twice this month" is that display wearing a
    different hat. Somebody who bought two packs knows they bought two packs.
    """

    model_config = ConfigDict(from_attributes=True)

    #: Whether the upgrade is the primary control and the top-up the secondary
    #: one — §4.5 point 2, on the second purchase in a rolling thirty days.
    #:
    #: **Never a gate.** Point 4 is explicit: *"Never gate the top-up behind the
    #: upgrade prompt. One tap to decline, always."* This says which is bigger,
    #: never which is available, and there is no field here that could withhold
    #: one — a top-up is always purchasable and the schema has no way to say
    #: otherwise.
    upgrade_first: bool

    #: The rung to offer, or null at the top of the ladder.
    #:
    #: Null is a real answer rather than a missing one. `pro_annual` is the same
    #: capability on a different period and `teams` has a *smaller* upload cap,
    #: so neither is on `UPGRADE_LADDER` — and a Pro subscriber buying their
    #: third pack has genuinely nothing to be steered toward. Steering them
    #: anyway would take money for a plan that gives them no more room.
    next_tier: str | None = None


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
