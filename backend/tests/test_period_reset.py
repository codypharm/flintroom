"""Monthly allowance reset.

Product.md §4.4: allowance is monthly with no roll-over, and the free tier's
15 minutes are lifetime rather than monthly. The reset is lazy — it happens on
the next read rather than on a schedule — so a dropped RevenueCat webhook costs
nothing and there is no cron to fail silently.
"""

from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from app.modules.billing.schemas import Bucket, EntryReason

STARTER_SECONDS = 90 * 60


@pytest.fixture
def starter(account):
    account.entitlement_tier = "starter"
    return account


async def test_a_lapsed_period_grants_the_new_allowance_once(ledger, db, starter):
    """Three missed boundaries still grant one allowance, not three.

    A user who does not open the app for a quarter has three elapsed periods.
    The reset must walk to the *current* period and grant for that one — a loop
    that grants per elapsed period hands out a quarter's minutes at once.
    """
    starter.period_id = 1
    starter.period_ends_at = datetime(2026, 5, 1, tzinfo=UTC)
    await db.commit()

    with freeze_time("2026-08-11"):
        balance = await ledger.ensure_current_period(user_id=starter.user_id)

    assert balance.allowance_seconds == STARTER_SECONDS

    grants = [
        e
        for e in await ledger.entries(user_id=starter.user_id)
        if e.reason is EntryReason.GRANT_ALLOWANCE
    ]
    assert len(grants) == 1


async def test_unspent_allowance_does_not_roll_over(ledger, db, starter):
    """No roll-over — Product.md §4.4. The remainder expires as its own entry.

    Writing the expiry rather than overwriting the balance keeps the entry log
    able to reproduce the cached balance, which is the whole reason the ledger
    is append-only.
    """
    starter.period_id = 1
    starter.period_ends_at = datetime(2026, 8, 1, tzinfo=UTC)
    starter.balance_allowance_seconds = 1200
    await db.commit()

    with freeze_time("2026-08-11"):
        balance = await ledger.ensure_current_period(user_id=starter.user_id)

    assert balance.allowance_seconds == STARTER_SECONDS

    entries = await ledger.entries(user_id=starter.user_id)
    expiries = [e for e in entries if e.reason is EntryReason.EXPIRE_ALLOWANCE]
    assert [(e.bucket, e.delta_seconds) for e in expiries] == [(Bucket.ALLOWANCE, -1200)]

    replayed = sum(e.delta_seconds for e in entries if e.bucket is Bucket.ALLOWANCE)
    assert replayed == balance.allowance_seconds - 1200


async def test_reset_leaves_free_and_topup_alone(ledger, db, starter):
    """Free minutes are lifetime and top-up never expires.

    Product.md §4.4 grants the free tier 15 minutes *lifetime*, and §4.5 states
    top-up minutes never expire. Only the monthly allowance turns over.
    """
    starter.period_id = 1
    starter.period_ends_at = datetime(2026, 8, 1, tzinfo=UTC)
    starter.balance_free_seconds = 400
    starter.balance_topup_seconds = 1200
    await db.commit()

    with freeze_time("2026-08-11"):
        balance = await ledger.ensure_current_period(user_id=starter.user_id)

    assert balance.free_seconds == 400
    assert balance.topup_seconds == 1200


async def test_reset_inside_the_period_changes_nothing(ledger, db, starter):
    """Reading twice inside one period must not re-grant."""
    starter.period_id = 1
    starter.period_ends_at = datetime(2026, 9, 1, tzinfo=UTC)
    starter.balance_allowance_seconds = 600
    await db.commit()

    with freeze_time("2026-08-11"):
        await ledger.ensure_current_period(user_id=starter.user_id)
        balance = await ledger.ensure_current_period(user_id=starter.user_id)

    assert balance.allowance_seconds == 600
    assert await ledger.entries(user_id=starter.user_id) == []


async def test_a_free_account_gets_no_monthly_allowance(ledger, db, account):
    """The free tier's 15 minutes are lifetime, so nothing renews.

    Granting a free account 15 minutes every month would quietly turn the
    lifetime trial into a subscription nobody pays for.
    """
    account.period_id = 1
    account.period_ends_at = datetime(2026, 5, 1, tzinfo=UTC)
    await db.commit()

    with freeze_time("2026-08-11"):
        balance = await ledger.ensure_current_period(user_id=account.user_id)

    assert balance.allowance_seconds == 0
    assert await ledger.entries(user_id=account.user_id) == []


async def test_the_period_advances_past_every_elapsed_boundary(ledger, db, starter):
    """After a reset the account sits in the current period, not the next one.

    If the boundary only advances by one month, the very next read resets again
    and grants a second allowance.
    """
    starter.period_id = 1
    starter.period_ends_at = datetime(2026, 5, 1, tzinfo=UTC)
    await db.commit()

    with freeze_time("2026-08-11"):
        await ledger.ensure_current_period(user_id=starter.user_id)
        await db.refresh(starter)
        assert starter.period_ends_at > datetime(2026, 8, 11, tzinfo=UTC)

        # A second read in the same period must be inert.
        await ledger.ensure_current_period(user_id=starter.user_id)

    grants = [
        e
        for e in await ledger.entries(user_id=starter.user_id)
        if e.reason is EntryReason.GRANT_ALLOWANCE
    ]
    assert len(grants) == 1
    assert starter.period_ends_at - datetime(2026, 8, 11, tzinfo=UTC) <= timedelta(days=31)
