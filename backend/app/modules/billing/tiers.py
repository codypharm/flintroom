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
