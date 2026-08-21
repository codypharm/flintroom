"""The rule that stops the product farming the people who like it most.

`Product.md` §4.5, marked **required**, and `CLAUDE.md` repeats it under Metering
Rules. Both had it and nothing implemented it.

The reasoning is the part worth keeping: *"Top-ups carry the highest margin in
the product and are bought at the user's worst moment — out of minutes,
presenting tomorrow. Charging a premium there is defensible only if the product
actively steers users away from repeating it."* And: *"A user who tops up three
times in a month is a pricing failure, not a revenue win."*

So this is a trust mechanic, not a growth feature, which is why it sits beside
the metering boundary rather than in a backlog.

**Point 3 needed no code, and that is worth knowing before reading the rest.**
*"The minutes are the credit."* Top-up minutes live in their own bucket that
`ensure_current_period` never writes off, so a user who tops up and then
subscribes holds both — and `grant_topup`'s own docstring already said this is
what makes §4.5 true. The rule was satisfied by construction. What was missing
is the *steering*, and one test below pins the credit as a rule rather than
leaving it an incidental property nobody would notice losing.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.core.database import db_now
from app.modules.billing.models import Account, LedgerEntry
from app.modules.billing.schemas import Bucket, EntryReason

pytestmark = pytest.mark.asyncio


async def _topped_up(db, account, *, ago: timedelta = timedelta(days=1)) -> None:
    """A pack this account bought `ago`.

    Written directly rather than through `grant_topup`, for one reason: the
    entry's age is the whole variable and `created_at` is a server default.
    Granting and then updating the row would test the same thing through two
    statements instead of one.
    """
    db.add(
        LedgerEntry(
            user_id=account.user_id,
            bucket=Bucket.TOPUP,
            delta_seconds=1200,
            reason=EntryReason.GRANT_TOPUP,
            idempotency_key=f"topup:{uuid.uuid4()}",
            created_at=await db_now(db) - ago,
        )
    )
    await db.commit()


async def test_a_first_purchase_leads_with_the_top_up(client, bearer, funded_account):
    """The tracer, and the case that must not break.

    §4.5 point 1 keeps the top-up primary the first time and shows the upgrade
    *alongside* it. Somebody out of minutes the night before a board readout is
    not shopping for a subscription — they need twenty minutes, and a screen
    that leads with a monthly plan has misread the moment.
    """
    response = await client.get(
        "/v1/purchase-options", headers=bearer(funded_account.user_id)
    )

    assert response.status_code == 200
    assert response.json()["upgrade_first"] is False


async def test_a_second_purchase_in_the_window_leads_with_the_upgrade(
    db, client, bearer, funded_account
):
    """§4.5 point 2, and the whole of the rule.

    They bought a pack; the one in front of them now is the second. The steering
    has to happen *before* they pay — a prompt after the fact is a receipt with
    an opinion.
    """
    await _topped_up(db, funded_account)

    response = await client.get(
        "/v1/purchase-options", headers=bearer(funded_account.user_id)
    )

    assert response.json()["upgrade_first"] is True


async def test_a_pack_older_than_the_window_is_not_a_repeat(
    db, client, bearer, funded_account
):
    """Rolling thirty days, so somebody who tops up twice a year is not steered.

    The rule is about a *rate*: "a user who tops up three times in a month is a
    pricing failure". Two purchases five weeks apart is a person whose plan fits
    them, occasionally needing more — telling them to subscribe would be wrong
    on the facts.
    """
    await _topped_up(db, funded_account, ago=timedelta(days=31))

    response = await client.get(
        "/v1/purchase-options", headers=bearer(funded_account.user_id)
    )

    assert response.json()["upgrade_first"] is False


async def test_one_account_does_not_steer_another(db, client, bearer, funded_account):
    """Per account, which is also what keeps the read shardable by `user_id`.

    `docs/deferred-scale-work.md` forbids a cross-user aggregate on this path,
    and this is not one.
    """
    stranger = Account(user_id=uuid.uuid4(), entitlement_tier="free")
    db.add(stranger)
    await db.commit()
    for _ in range(3):
        await _topped_up(db, stranger)

    response = await client.get(
        "/v1/purchase-options", headers=bearer(funded_account.user_id)
    )

    assert response.json()["upgrade_first"] is False


async def test_the_top_of_the_ladder_has_nothing_to_be_steered_to(
    db, client, bearer, funded_account
):
    """A Pro subscriber buying their third pack is not a pricing failure.

    `UPGRADE_LADDER` stops at `pro` deliberately — `pro_annual` is the same
    capability on a different period and `teams` has a *smaller* upload cap, so
    neither is somewhere to send anybody. Leading with an upgrade that does not
    exist would leave a screen with a primary button and nothing to put in it,
    and offering one anyway would take money for no more room.
    """
    from sqlalchemy import update

    await db.execute(
        update(Account)
        .where(Account.user_id == funded_account.user_id)
        .values(entitlement_tier="pro")
    )
    await db.commit()
    await _topped_up(db, funded_account)

    body = (
        await client.get(
            "/v1/purchase-options", headers=bearer(funded_account.user_id)
        )
    ).json()

    assert body["next_tier"] is None
    assert body["upgrade_first"] is False


async def test_the_offer_names_the_rung_it_would_send_them_to(
    db, client, bearer, funded_account
):
    """So the screen can price it without a second table of its own.

    A client holding its own tier ladder is a client free to offer a plan we
    retired, at a price we no longer charge.
    """
    from sqlalchemy import update

    await db.execute(
        update(Account)
        .where(Account.user_id == funded_account.user_id)
        .values(entitlement_tier="free")
    )
    await db.commit()

    body = (
        await client.get(
            "/v1/purchase-options", headers=bearer(funded_account.user_id)
        )
    ).json()

    assert body["next_tier"] == "starter"


async def test_upgrading_leaves_bought_minutes_alone(db, ledger, funded_account):
    """**§4.5 point 3 — "the minutes are the credit" — pinned as a rule.

    This already worked, and that is exactly why it needs a test. Top-up minutes
    sit in their own bucket that `ensure_current_period` never writes off, so a
    user who tops up and then subscribes holds both. It is true by construction
    rather than by intent, and a construction nobody asserted is one a later
    refactor can quietly lose.

    Losing it is the failure the 2026-08-16 revision was written around: the
    rule stopped promising a price discount precisely because the ledger already
    keeps these minutes. If the bucket ever stopped surviving an upgrade, §4.5
    would be promising something untrue with nothing to catch it.
    """
    await ledger.grant_topup(
        user_id=funded_account.user_id, seconds=1200, idempotency_key="pack-1"
    )

    await ledger.apply_subscription(
        user_id=funded_account.user_id,
        tier="pro",
        period_ends_at=await db_now(db) + timedelta(days=30),
    )

    balance = await ledger.balance(user_id=funded_account.user_id)
    assert balance.topup_seconds == 1200
