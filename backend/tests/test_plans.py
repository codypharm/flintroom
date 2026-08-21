"""What a plan gets you, published — #95.

The buy screen rendered entirely from the store's `Sellable`, so with no
offering configured it had nothing to draw and fell back to one sentence. The
architect's verdict on seeing it was "where are the plans and the likes", and it
was the right one: I drew the seam in the wrong place.

**The store owns what somebody is charged. We own what they get.** Every fact
below already existed in `billing/tiers.py` — allowance, panel size, upload cap,
retention, whether a tier may author an archetype — and none of it needed an
offering to be true.

Published rather than shipped in the app, on the argument `/v1/materials/limits`
already won: *"this exists so the tier table has one home rather than a second
copy shipped in an app release."* A client holding its own ladder is a client
free to offer a plan we retired at a price we no longer charge.

**No price here.** That is the store's, in the buyer's currency, after whatever
regional adjustment applies — and a screen carrying its own would state one
number and charge another.
"""

from __future__ import annotations

import pytest
from sqlalchemy import update

from app.modules.billing.models import Account
from app.modules.billing.tiers import (
    MAX_PANEL_SIZE,
    MONTHLY_ALLOWANCE_SECONDS,
    UPGRADE_LADDER,
)

pytestmark = pytest.mark.asyncio


async def read(client, bearer, account) -> list[dict]:
    response = await client.get("/v1/plans", headers=bearer(account.user_id))
    assert response.status_code == 200, response.text
    return response.json()


async def test_it_publishes_the_rungs_somebody_can_actually_climb(
    client, bearer, funded_account
):
    """The tracer, and `UPGRADE_LADDER` is the set on purpose.

    `pro_annual` is the same capability on another billing period and `teams`
    has a *smaller* upload cap than pro, so neither is a rung — and a pricing
    screen that listed them as if they were would be offering somebody less for
    more.
    """
    plans = await read(client, bearer, funded_account)

    assert [plan["name"] for plan in plans] == list(UPGRADE_LADDER)


async def test_a_plan_says_what_it_gets_you_rather_than_what_it_costs(
    client, bearer, funded_account
):
    """§4.6: *"Lead with the largest honest unit. '3 hours of executive-level
    interrogation every month' reads generously. '15 credits' reads rationed."*

    None of this is expressible from a `Sellable`, and all of it was sitting in
    `tiers.py` while the screen showed a sentence.
    """
    plans = await read(client, bearer, funded_account)
    pro = next(plan for plan in plans if plan["name"] == "pro")

    assert pro["minutes"] == MONTHLY_ALLOWANCE_SECONDS["pro"] // 60
    assert pro["seats"] == MAX_PANEL_SIZE["pro"]
    assert pro["retention_days"] == 365
    assert pro["may_author"] is True
    assert "price" not in pro


async def test_the_free_tier_says_its_minutes_do_not_come_back(
    client, bearer, funded_account
):
    """Fifteen minutes *for life*, not per month — and the difference is the
    whole of what the free tier is.

    A card reading "15 minutes" beside "90 minutes a month" would be read as a
    smaller monthly allowance, which is a more generous plan than the one that
    exists. Understating a paid tier is a poor sales screen; overstating a free
    one is a promise the ledger will refuse to keep.
    """
    plans = await read(client, bearer, funded_account)
    free = next(plan for plan in plans if plan["name"] == "free")

    assert free["minutes"] == 15
    assert free["renews"] is False
    assert next(p for p in plans if p["name"] == "pro")["renews"] is True


async def test_it_says_which_one_the_caller_is_already_on(
    db, client, bearer, funded_account
):
    """So the screen can mark it rather than sell it back to them.

    Answered here rather than inferred by the client from a tier string, because
    the client would then need its own copy of what `pro_annual` and `teams` map
    onto — the second table this endpoint exists to prevent.
    """
    await db.execute(
        update(Account)
        .where(Account.user_id == funded_account.user_id)
        .values(entitlement_tier="starter")
    )
    await db.commit()

    plans = await read(client, bearer, funded_account)

    assert [plan["name"] for plan in plans if plan["current"]] == ["starter"]


async def test_a_tier_off_the_ladder_still_gets_an_honest_answer(
    db, client, bearer, funded_account
):
    """`pro_annual` is not a rung, and somebody on it is not nowhere.

    Nothing is marked current, which is true — none of the rungs listed is the
    plan they hold — and the screen must not answer that by highlighting the
    wrong one. Silence beats a guess about what somebody is paying for.
    """
    await db.execute(
        update(Account)
        .where(Account.user_id == funded_account.user_id)
        .values(entitlement_tier="pro_annual")
    )
    await db.commit()

    plans = await read(client, bearer, funded_account)

    assert [plan["name"] for plan in plans] == list(UPGRADE_LADDER)
    assert not any(plan["current"] for plan in plans)


async def test_every_tier_says_the_unmetered_part_out_loud(
    client, bearer, funded_account
):
    """§4.4: *"All tiers include unmetered debrief and sparring."* §4.6: *"Say
    what is unlimited, prominently... at the top of every tier card, not in a
    footnote."*

    On every plan rather than stated once, because it is the answer to "what do
    I actually get for this" on each of them — and because a client that had to
    remember to add it is a client that will forget on one card.
    """
    plans = await read(client, bearer, funded_account)

    assert all(plan["unmetered_coaching"] for plan in plans)
