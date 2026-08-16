"""What each tier may upload, and which tier the refusal names.

`docs/ingestion.md` publishes two of these figures on tier cards and keeps two
unpublished as backstops. That asymmetry is why the ladder is tested rather than
eyeballed: an unpublished number can be tightened silently, and a published one
cannot — so the tier a refusal names is a pricing statement, and it should be
the cheapest true one rather than the most expensive plausible one.

Every figure here is provisional and rests on an unverified ~$0.01 per page.
These tests hold the *shape* — that the ladder is consistent, that no tier is
missing a cap — not the values, which move when §4.3 measures a page.
"""

import pytest

from app.core.config import Settings
from app.modules.ingestion.extractor import DEFAULT_DAILY_PAGE_CEILING
from app.modules.billing.tiers import (
    MAX_PAGES_PER_MATERIAL,
    MAX_UPLOAD_BYTES,
    MONTHLY_ALLOWANCE_SECONDS,
    MONTHLY_PAGE_BUDGET,
    UPGRADE_LADDER,
    FREE_TIER,
    next_tier_above,
    smallest_tier_accepting,
)

MB = 1024 * 1024


def test_every_tier_an_account_can_hold_has_both_caps():
    """The drift guard: a new tier without a cap is a `KeyError` at upload time.

    Derived from the allowance table rather than listed again, so adding a tier
    to pricing and forgetting it here fails in a test run instead of in the
    first upload by whoever bought it.
    """
    tiers = set(MONTHLY_ALLOWANCE_SECONDS) | {FREE_TIER}

    assert tiers <= set(MAX_UPLOAD_BYTES)
    assert tiers <= set(MAX_PAGES_PER_MATERIAL)


def test_the_ladder_only_goes_up():
    """Each rung accepts strictly more than the one below it.

    Not decoration. `smallest_tier_accepting` walks this order and returns the
    first tier that fits, which is only the cheapest sufficient answer if the
    order is monotonic — an out-of-order rung would quietly start naming an
    over-sell.
    """
    caps = [MAX_UPLOAD_BYTES[tier] for tier in UPGRADE_LADDER]

    assert caps == sorted(caps)
    assert len(set(caps)) == len(caps)


@pytest.mark.parametrize(
    ("byte_size", "expected"),
    [
        (1 * MB, "free"),
        (12 * MB, "starter"),
        (40 * MB, "pro"),
    ],
)
def test_a_refusal_names_the_cheapest_tier_that_would_take_the_file(
    byte_size, expected
):
    """The cheapest one, not the best one.

    A 12MB deck is refused on free and accepted on starter, so starter is the
    honest answer. Naming pro instead would be an upsell dressed as a fact, in a
    message whose whole credibility comes from being neither.
    """
    assert smallest_tier_accepting(byte_size) == expected


def test_a_file_no_tier_accepts_names_no_tier():
    """Above the top rung there is nothing to sell, so the refusal sells nothing.

    The alternative — naming the largest tier anyway — takes money for a plan
    that still will not accept the file, which is the one outcome a paywall in
    this product may not produce.
    """
    assert smallest_tier_accepting(4096 * MB) is None


def test_teams_is_not_on_the_upgrade_ladder():
    """It is a seat count, not a size step, and its cap sits below pro's.

    Putting it on the ladder would make a pro user's oversized file suggest
    teams, which is more expensive and accepts *less*. Teams users over their
    cap are told the cap and nothing else — a real limit with no honest upsell
    behind it, which is the correct thing to say.
    """
    assert "teams" not in UPGRADE_LADDER
    assert MAX_UPLOAD_BYTES["teams"] < MAX_UPLOAD_BYTES["pro"]


def test_the_next_rung_is_what_the_limits_endpoint_offers():
    """The client refuses locally, so it needs the next rung before any file.

    Distinct from `smallest_tier_accepting`, which needs a file to answer. This
    is the one the tier card is drawn from.
    """
    assert next_tier_above("free") == "starter"
    assert next_tier_above("starter") == "pro"
    assert next_tier_above("pro") is None


def test_a_tier_off_the_ladder_has_no_next_rung():
    """`pro_annual` is already at the top cap; `teams` has nowhere sideways.

    Neither should produce an upgrade prompt, and neither should raise — a
    `KeyError` here would be a 500 on a read-only endpoint.
    """
    assert next_tier_above("pro_annual") is None
    assert next_tier_above("teams") is None


def test_the_daily_ceiling_clears_the_largest_file_a_plan_sells():
    """A ceiling below a per-file cap refuses a file the tier card offered.

    This was live: pro sold 300 pages per file against a 200-page daily
    ceiling, so a user who re-exported their deck to fix a typo had the second
    upload held for twenty-four hours — an ordinary act read as a runaway. The
    two numbers live in different files for good reasons (one is pricing, one is
    a safety dial), which is exactly why nothing else would notice them drifting
    apart again.

    Twice over rather than merely clear. Once is not enough: uploading the same
    deck twice in an evening is the normal case, not the edge one.
    """
    largest = max(MAX_PAGES_PER_MATERIAL.values())

    assert DEFAULT_DAILY_PAGE_CEILING >= 2 * largest
    # The setting and the module default are two copies of one number, and a
    # deployment that sets neither must get the safe one.
    assert Settings.model_fields["daily_page_ceiling"].default == (
        DEFAULT_DAILY_PAGE_CEILING
    )


def test_the_daily_ceiling_still_bites_somewhere():
    """The other side: a ceiling this high has to remain a circuit breaker.

    Against the *loosest* budget, not every budget. On the tighter tiers the
    monthly figure binds first and the daily ceiling never fires — free's
    hundred lifetime pages are below it outright, and starter's whole month is
    six hundred. That is not the ceiling failing; it is a cheaper limit reaching
    the same runaway sooner, which is the order these controls should fire in.

    Where it has to work is the tier whose monthly budget is loose enough to
    lose in an afternoon. If one day could exhaust even that, the daily limit
    would be decoration and the monthly budget would be the only thing between
    a loop and the whole allowance.
    """
    assert DEFAULT_DAILY_PAGE_CEILING < max(MONTHLY_PAGE_BUDGET.values())
