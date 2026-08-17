"""What each entitlement tier includes: minutes, and what may be uploaded.

Figures from Product.md §4.4. They are policy, not arithmetic — they move when
pricing moves, and pricing cannot move without the §4.3 cost-instrumentation
task behind it.

The free tier is deliberately absent rather than set to zero minutes: its 15
minutes are *lifetime*, granted once at signup into the free bucket, and nothing
about it renews monthly.
"""

MONTHLY_ALLOWANCE_SECONDS: dict[str, int] = {
    "starter": 90 * 60,
    "pro": 180 * 60,
    "pro_annual": 180 * 60,
    "teams": 90 * 60,
}

#: Granted once at signup, never renewed. Product.md §4.4.
FREE_TIER_LIFETIME_SECONDS = 15 * 60

#: The tier every account starts on. Not a key in the table above: the free
#: tier's minutes are lifetime rather than monthly, so it has no renewing
#: allowance to look up.
FREE_TIER = "free"


# --- Material limits ------------------------------------------------------
#
# Four controls doing three different jobs (`docs/ingestion.md`). The two below
# are the *published* ones, printed on tier cards, and they inherit the terms in
# this module's docstring with one extra clause: publishing a limit converts it
# from a dial into a promise. An unpublished backstop can be tightened in a
# deploy; a tier card cannot be tightened without telling customers.
#
# So these figures may be built against now and may not appear on a real pricing
# page until §4.3 has measured a page. They rest on an unverified ~$0.01/page,
# which is the weakest number in the ingestion design.

#: The largest single upload, per tier. Enforced in the signature rather than
#: after the fact — see `ObjectStorage.presign_put`.
MAX_UPLOAD_BYTES: dict[str, int] = {
    "free": 10 * 1024 * 1024,
    "starter": 25 * 1024 * 1024,
    "pro": 100 * 1024 * 1024,
    "pro_annual": 100 * 1024 * 1024,
    "teams": 25 * 1024 * 1024,
}

#: Pages extracted from one material. Cannot be checked before the upload —
#: counting pages means reading the file — so this refusal happens after the
#: bytes land, unlike the byte cap above.
MAX_PAGES_PER_MATERIAL: dict[str, int] = {
    "free": 20,
    "starter": 100,
    "pro": 300,
    "pro_annual": 300,
    "teams": 100,
}

#: Pages one account may have extracted within its entitlement period.
#:
#: **Unpublished, and that is what keeps it a dial.** The two caps above are on
#: tier cards; this one is a backstop in the same category as §4.7's per-account
#: daily spend ceiling. Real use is 40–80 pages a month against 600 allowed, so
#: no legitimate user meets it — and leaving it unpublished means it can be
#: tightened against measured `extraction_costs` without notifying customers,
#: which matters because it rests on an unverified ~$0.01 per page.
#:
#: The window is the account's own entitlement period, so this moves with the
#: minutes allowance rather than with the calendar. Free is absent for the same
#: reason it is absent from `MONTHLY_ALLOWANCE_SECONDS`: it has no renewing
#: period at all.
MONTHLY_PAGE_BUDGET: dict[str, int] = {
    "starter": 600,
    "pro": 1200,
    "pro_annual": 1200,
    "teams": 600,
}

#: The free tier's whole allowance of extraction, ever.
#:
#: Lifetime rather than monthly, exactly like `FREE_TIER_LIFETIME_SECONDS`. A
#: renewing page budget on a tier whose minutes do not renew is an unlimited
#: extraction faucet: sign up, never start a session, extract decks forever at
#: our cost with no metered minute ever consumed against them.
FREE_TIER_LIFETIME_PAGES = 100


def page_budget(tier: str) -> int:
    """How many pages this tier may extract in one window.

    Every unknown tier falls to the free allowance rather than to a generous
    default, which is the direction a missing entry should fail in: a tier added
    to pricing and forgotten here throttles early and visibly, instead of
    quietly granting unlimited extraction to whoever bought it.
    """
    return MONTHLY_PAGE_BUDGET.get(tier, FREE_TIER_LIFETIME_PAGES)


#: The rungs a user can actually climb, cheapest first.
#:
#: Neither `pro_annual` nor `teams` is on it, for opposite reasons. `pro_annual`
#: is the same capability on a different billing period, so it is already at the
#: top and has nowhere to go. `teams` is a seat count whose upload cap sits
#: *below* pro's — offering it as an upgrade would charge more for less, which is
#: the one thing a refusal message may not do.
UPGRADE_LADDER: tuple[str, ...] = ("free", "starter", "pro")


def smallest_tier_accepting(byte_size: int) -> str | None:
    """The cheapest tier whose upload cap would take this file, if any.

    What an oversized-upload refusal names. The cheapest rather than the largest
    on purpose: the message's entire credibility rests on reading as a fact, and
    a fact that happens to sell the most expensive plan is not one. `None` when
    the file is over the top rung — there is nothing to offer, and offering
    something anyway would take money for a plan that still refuses the file.
    """
    for tier in UPGRADE_LADDER:
        if byte_size <= MAX_UPLOAD_BYTES[tier]:
            return tier
    return None


def next_tier_above(tier: str) -> str | None:
    """The rung above this one, or nothing.

    What the limits endpoint offers, before any file exists to measure. Returns
    `None` rather than raising for a tier that is off the ladder: this is read
    by a GET whose only job is to describe the caller, and an unrecognised tier
    there is a missing upsell, not a server error.
    """
    if tier not in UPGRADE_LADDER:
        return None
    rung = UPGRADE_LADDER.index(tier) + 1
    return UPGRADE_LADDER[rung] if rung < len(UPGRADE_LADDER) else None


# --- Store products -------------------------------------------------------
#
# What a store calls a plan, and what it means here. `docs/billing-setup.md` is
# the dashboard work that creates these; this is the half that reads them back.
#
# **These identifiers are chosen, not observed.** No store account exists yet, so
# they are the naming decision made in advance rather than strings read off a
# real purchase. Two things make that safe to build against:
#
#   - An identifier absent from these tables is refused with an audit row naming
#     the string that arrived, never granted-nothing-quietly. The first real
#     purchase either works or says exactly what to correct.
#   - Play may report a subscription as `<subscription_id>:<base_plan_id>` rather
#     than the bare id. If it does, the correction is an entry here.
#
# Keyed on the product rather than the RevenueCat entitlement, because
# entitlement is too coarse: Pro and Pro Annual share one, and they are different
# tiers to us — same minutes, different revenue, different margin in §4.4.

#: Store product → entitlement tier. Subscriptions only.
SUBSCRIPTION_TIERS: dict[str, str] = {
    "flintroom_starter_monthly": "starter",
    "flintroom_pro_monthly": "pro",
    "flintroom_pro_annual": "pro_annual",
    "flintroom_teams_monthly": "teams",
}

#: Store product → seconds granted, for the consumable packs in §4.5.
#:
#: Seconds rather than minutes because the ledger is in seconds throughout, and
#: a unit conversion at one call site is a unit conversion that eventually
#: happens twice or not at all.
TOPUP_SECONDS: dict[str, int] = {
    "flintroom_topup_20": 20 * 60,
    "flintroom_topup_90": 90 * 60,
    "flintroom_topup_300": 300 * 60,
}


# --- The room -------------------------------------------------------------

#: How many archetypes one session may seat.
#:
#: **Not a cost control**, which makes it unlike every other cap in this module.
#: Only one archetype speaks per turn (`docs/panel-orchestration.md`), so the
#: selection step reads a roster and the composer reads a single persona — a
#: five-person panel bills within a rounding error of a three-person one. Nothing
#: here protects a margin.
#:
#: What it protects is the session. A ten-minute interrogation split six ways
#: gives everybody two questions and nobody a line of attack that develops, so
#: past a point a bigger room is a worse one. The tier ladder sells *assembling* a
#: room rather than crowding it.
#:
#: Three is the floor because §3.1's mixed panel — a champion, a skeptic and a
#: neutral — fits in three. §4.4 promises the free tier one complete experience
#: rather than a truncated taste, and a room without an ally is not that.
#:
#: Teams sits with Starter, as it does for every other capability here: §4.4
#: prices it at Starter level per seat and explicitly refuses to undercut the
#: standalone plan.
MAX_PANEL_SIZE: dict[str, int] = {
    "free": 3,
    "starter": 4,
    "pro": 5,
    "pro_annual": 5,
    "teams": 4,
}

#: Which tiers may author their own archetypes.
#:
#: §4.4 lists custom archetypes as a Pro capability, alongside priority voice
#: queue and prep-sheet export — *"Pro's value is in capability, not a bulk
#: rate."* Unlike panel size this is a genuine differentiator, because it is the
#: one panel feature that is not simply a number.
#:
#: Teams is **excluded**, following the same Starter-level rule as the table
#: above. It is the least obvious call in this module: a cohort programme wanting
#: one archetype written around its own curriculum is a plausible ask, and the
#: answer may well become yes once Teams has a buyer to ask.
CUSTOM_ARCHETYPE_TIERS: frozenset[str] = frozenset({"pro", "pro_annual"})


def max_panel_size(tier: str) -> int:
    """Seats in the room for this tier, defaulting to the free floor."""
    return MAX_PANEL_SIZE.get(tier, MAX_PANEL_SIZE[FREE_TIER])


def may_author_archetypes(tier: str) -> bool:
    """Whether this tier may write its own archetype."""
    return tier in CUSTOM_ARCHETYPE_TIERS


# --- Retained audio -------------------------------------------------------

#: How long a room's audio can still be played back, per tier, in days.
#:
#: Decided with the architect 2026-08-17, closing the "recording-retention
#: window" that `Product.md` §413 listed under *"Undecided, do not invent"*. See
#: `docs/session-retention.md` for the reasoning; the short version is below,
#: because the numbers look arbitrary without it.
#:
#: **The transcript is not on this table and never expires.** Text is tens of KB
#: and does not compound, so §4.4's "full session history" stays literally true
#: on every tier. Audio accrues every month, grows with every session ever run,
#: and keeps being charged for an account that churned a year ago — it is the
#: only cost in this product that behaves that way, so the window binds where
#: the cost actually is.
#:
#: **Free is thirty days, not seven, and that is not generosity.** A free
#: account is capped at fifteen minutes for life, so it produces ~2.7 MB and
#: then stops forever — even a hundred thousand of them retained indefinitely is
#: single-digit dollars a month. A short free window saves nothing measurable
#: while deleting the one artefact §4.4 says has to sell the subscription.
#:
#: **Pro is the only tier where retention compounds**, because it is the only
#: one generating tens of megabytes every month indefinitely. A year is what
#: makes "full session history" mean something without becoming an unbounded
#: promise, and a bounded number is a clean sentence for the privacy policy.
#:
#: Published, so the terms above the material limits apply with full force:
#: these can be lengthened in a deploy and cannot be shortened without telling
#: customers.
RECORDING_RETENTION_DAYS: dict[str, int] = {
    "free": 30,
    "starter": 90,
    "pro": 365,
    "pro_annual": 365,
    "teams": 90,
}
