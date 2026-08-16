"""What a purchase does to an account.

The second half of the webhook: the wall is proven in `test_revenuecat_webhook.py`
and everything here arrives having already been verified. What is under test is
the mapping from a store event to a tier and a number of seconds, which is where
money either lands correctly or does not land at all.

The identifiers are the ones in `docs/billing-setup.md`, chosen rather than
observed — no store account exists yet. That is safe in exactly one way: an
unrecognised product is refused with an audit row naming the string that arrived,
so the first real purchase either works or says precisely what to correct. It
would not be safe if an unknown product quietly granted nothing, which is the
version of this that looks like a working integration and silently sells minutes
nobody receives.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.actors import Actor, ActorContext
from app.core.errors import WebhookRejected
from app.modules.audit_log.models import AuditEvent
from app.modules.audit_log.schemas import AuditEventType
from app.modules.billing.billing import BillingService
from app.modules.billing.models import Account, LedgerEntry
from app.modules.billing.revenuecat import RevenueCatEvent
from app.modules.billing.schemas import Bucket
from app.modules.billing.service import LedgerService
from app.modules.billing.tiers import MONTHLY_ALLOWANCE_SECONDS

PRO = "flintroom_pro_monthly"
STARTER = "flintroom_starter_monthly"
TOPUP_90 = "flintroom_topup_90"


def event(**overrides) -> RevenueCatEvent:
    """A purchase as RevenueCat delivers one, with the fields billing reads."""
    expires = overrides.pop("expires", datetime.now(UTC) + timedelta(days=30))
    return RevenueCatEvent(
        id=overrides.pop("id", str(uuid.uuid4())),
        type=overrides.pop("type", "INITIAL_PURCHASE"),
        app_user_id=str(overrides.pop("app_user_id", uuid.uuid4())),
        product_id=overrides.pop("product_id", PRO),
        environment=overrides.pop("environment", "PRODUCTION"),
        expiration_at_ms=int(expires.timestamp() * 1000) if expires else None,
        **overrides,
    )


def billing(db) -> BillingService:
    """Billing as the webhook route builds it — attributed to the store."""
    return BillingService(db, actor=ActorContext(actor=Actor.WEBHOOK))


async def entries(db, user_id) -> list[LedgerEntry]:
    rows = await db.scalars(
        select(LedgerEntry)
        .where(LedgerEntry.user_id == user_id)
        .order_by(LedgerEntry.created_at, LedgerEntry.id)
    )
    return list(rows)


async def audited(db, event_type: AuditEventType) -> list[AuditEvent]:
    rows = await db.scalars(
        select(AuditEvent).where(AuditEvent.event_type == event_type.value)
    )
    return list(rows)


# --- Subscriptions --------------------------------------------------------


async def test_a_purchase_sets_the_tier_and_grants_the_month(db, account, ledger):
    """The tracer bullet: somebody paid, and the room opens.

    Both halves in one assertion because either alone is a bug users notice
    immediately — a tier without minutes is a plan that cannot start a session,
    and minutes without a tier is a free account with an unexplained balance.
    """
    await billing(db).handle(event(app_user_id=account.user_id))

    await db.refresh(account)
    assert account.entitlement_tier == "pro"
    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == (
        MONTHLY_ALLOWANCE_SECONDS["pro"]
    )


async def test_the_period_boundary_comes_from_the_store_not_from_thirty_days(
    db, account
):
    """Retires the placeholder `docs/minutes-ledger-and-sessions.md` flagged.

    The reset decision says the boundary follows the RevenueCat entitlement
    period rather than the calendar, and until this landed `PERIOD_LENGTH`
    advanced by a flat 30 days — so a subscriber billed on the 3rd drifted a day
    earlier every month against what they actually paid for.
    """
    expires = datetime.now(UTC) + timedelta(days=31)

    await billing(db).handle(event(app_user_id=account.user_id, expires=expires))

    await db.refresh(account)
    assert account.period_ends_at is not None
    assert abs((account.period_ends_at - expires).total_seconds()) < 2


async def test_a_renewal_expires_the_old_allowance_and_grants_the_new_one(
    db, account, ledger
):
    """No roll-over (§4.4), and the write-off is its own entry.

    Overwriting the balance instead would break the reconciliation that the
    append-only model exists for — replaying the entries would no longer
    reproduce the cached balance.
    """
    first = datetime.now(UTC) + timedelta(days=30)
    await billing(db).handle(event(app_user_id=account.user_id, expires=first))

    await billing(db).handle(
        event(
            app_user_id=account.user_id,
            type="RENEWAL",
            expires=first + timedelta(days=30),
        )
    )

    reasons = [entry.reason for entry in await entries(db, account.user_id)]
    assert reasons.count("grant_allowance") == 2
    assert reasons.count("expire_allowance") == 1
    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == (
        MONTHLY_ALLOWANCE_SECONDS["pro"]
    )


async def test_the_same_renewal_delivered_five_times_grants_once(db, account, ledger):
    """RevenueCat retries a non-200 five times, and retries are not the only way.

    Duplicate delivery is ordinary rather than exceptional, so the guard is the
    period itself: an event whose expiry the account has already advanced to has
    already been applied. Idempotency on the event id alone would not survive
    the store re-sending the same period under a new id.
    """
    expires = datetime.now(UTC) + timedelta(days=30)

    for _ in range(5):
        await billing(db).handle(
            event(app_user_id=account.user_id, type="RENEWAL", expires=expires)
        )

    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == (
        MONTHLY_ALLOWANCE_SECONDS["pro"]
    )


async def test_an_event_that_arrives_late_does_not_wind_the_period_back(
    db, account, ledger
):
    """Webhooks are not ordered, and an old one must not undo a new one.

    A `RENEWAL` for August delivered after September's would otherwise move the
    boundary backwards and grant a second allowance — a user who is paid up to
    September being told they renew in August, with double the minutes.
    """
    august = datetime.now(UTC) + timedelta(days=10)
    september = august + timedelta(days=30)

    await billing(db).handle(event(app_user_id=account.user_id, expires=september))
    await billing(db).handle(
        event(app_user_id=account.user_id, type="RENEWAL", expires=august)
    )

    await db.refresh(account)
    assert abs((account.period_ends_at - september).total_seconds()) < 2
    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == (
        MONTHLY_ALLOWANCE_SECONDS["pro"]
    )


async def test_an_upgrade_mid_period_changes_the_tier(db, account):
    """`PRODUCT_CHANGE` with the same expiry still has to move the tier.

    The period is unchanged — they are the same subscription — so a handler that
    keys everything off the boundary does nothing at all, and the user pays Pro
    prices on Starter limits until their next renewal.
    """
    expires = datetime.now(UTC) + timedelta(days=30)
    await billing(db).handle(
        event(app_user_id=account.user_id, product_id=STARTER, expires=expires)
    )

    await billing(db).handle(
        event(
            app_user_id=account.user_id,
            type="PRODUCT_CHANGE",
            product_id=PRO,
            expires=expires,
        )
    )

    await db.refresh(account)
    assert account.entitlement_tier == "pro"


# --- Losing a subscription ------------------------------------------------


async def test_an_expiry_drops_the_account_to_free(db, account):
    """Access actually ended, so the tier has to say so."""
    await billing(db).handle(event(app_user_id=account.user_id))

    await billing(db).handle(
        event(app_user_id=account.user_id, type="EXPIRATION", expires=None)
    )

    await db.refresh(account)
    assert account.entitlement_tier == "free"


async def test_a_cancellation_leaves_the_subscription_running(db, account, ledger):
    """Auto-renew off is not access off, and the difference is a month.

    `CANCELLATION` fires when somebody turns off renewal — they have paid
    through the end of the period and are entitled to every minute of it.
    Revoking here would take away time already bought, from a user who has just
    signalled they are wavering.
    """
    await billing(db).handle(event(app_user_id=account.user_id))

    await billing(db).handle(
        event(app_user_id=account.user_id, type="CANCELLATION")
    )

    await db.refresh(account)
    assert account.entitlement_tier == "pro"
    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds > 0


async def test_a_refund_revokes_immediately(db, account):
    """A refund arrives as a cancellation, and it is the one that must revoke.

    RevenueCat reports both under `CANCELLATION`; `cancel_reason` is the only
    thing separating "I will not renew" from "give me my money back". Treating
    them alike either takes a paid month away from someone who cancelled, or
    leaves a refunded user on a paid tier.
    """
    await billing(db).handle(event(app_user_id=account.user_id))

    await billing(db).handle(
        event(
            app_user_id=account.user_id,
            type="CANCELLATION",
            cancel_reason="CUSTOMER_SUPPORT",
        )
    )

    await db.refresh(account)
    assert account.entitlement_tier == "free"


# --- Top-ups --------------------------------------------------------------


async def test_a_top_up_adds_minutes_that_do_not_touch_the_tier(db, account, ledger):
    """§4.5: top-up minutes sit alongside the allowance and never expire.

    Into their own bucket, which is what stops `ensure_current_period` writing
    them off at the next boundary — the failure would be a user losing minutes
    they paid cash for, at a moment they did not act.
    """
    await billing(db).handle(
        event(app_user_id=account.user_id, type="NON_RENEWING_PURCHASE",
              product_id=TOPUP_90, expires=None)
    )

    await db.refresh(account)
    assert account.entitlement_tier == "free"
    balance = await ledger.balance(user_id=account.user_id)
    assert balance.topup_seconds == 90 * 60
    assert balance.allowance_seconds == 0


async def test_the_same_top_up_delivered_twice_is_granted_once(db, account, ledger):
    """Idempotent on the event id, because there is no period to key on.

    A subscription has a boundary that makes a duplicate obvious; a consumable
    has nothing but the event. Without this, one retry is one free pack — and
    RevenueCat retries five times.
    """
    purchase = event(
        app_user_id=account.user_id, type="NON_RENEWING_PURCHASE",
        product_id=TOPUP_90, expires=None,
    )

    await billing(db).handle(purchase)
    await billing(db).handle(purchase)

    assert (await ledger.balance(user_id=account.user_id)).topup_seconds == 90 * 60


async def test_two_different_top_ups_both_land(db, account, ledger):
    """The guard above must key on the event, not on the product.

    Buying the same pack twice in a week is the behaviour §4.5 is explicitly
    designed around — it is what triggers the credit-toward-upgrade prompt — so
    collapsing them would break the feature and steal from the user.
    """
    for _ in range(2):
        await billing(db).handle(
            event(app_user_id=account.user_id, type="NON_RENEWING_PURCHASE",
                  product_id=TOPUP_90, expires=None)
        )

    assert (await ledger.balance(user_id=account.user_id)).topup_seconds == 2 * 90 * 60


# --- Refusals -------------------------------------------------------------


async def test_a_product_we_do_not_recognise_is_refused_loudly(db, account):
    """The guard that makes chosen identifiers safe to build against.

    No store account exists yet, so every identifier in the table is a decision
    rather than an observation — and Play may report a base-plan suffix nobody
    chose. Granting nothing quietly would look exactly like a working
    integration while selling minutes that never arrive. The audit row names the
    string that actually arrived, which is the correction.
    """
    with pytest.raises(WebhookRejected):
        await billing(db).handle(
            event(app_user_id=account.user_id, product_id="flintroom_pro_monthly:p1m")
        )

    (rejected,) = await audited(db, AuditEventType.WEBHOOK_REJECTED)
    assert rejected.context["product_id"] == "flintroom_pro_monthly:p1m"
    await db.refresh(account)
    assert account.entitlement_tier == "free"


async def test_a_sandbox_purchase_grants_nothing(db, account, ledger):
    """A licence tester must not be able to mint minutes against production.

    Play testers buy every product without being charged, and the events are
    otherwise identical to real ones — `environment` is the only thing telling
    them apart. Refused rather than ignored, so a staging deployment that
    genuinely wants them fails visibly rather than silently doing nothing.
    """
    with pytest.raises(WebhookRejected):
        await billing(db).handle(
            event(app_user_id=account.user_id, environment="SANDBOX")
        )

    await db.refresh(account)
    assert account.entitlement_tier == "free"
    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == 0


async def test_a_purchase_for_an_account_we_do_not_have_is_refused(db):
    """`app_user_id` is our id, and a value that is not one is not a guess to make.

    Creating an account here would let anyone who can forge a signed event
    populate our user table. Refusing means a real purchase that cannot be
    attributed becomes an audit row somebody has to look at, which is the correct
    amount of friction for money arriving for a user who does not exist.
    """
    with pytest.raises(WebhookRejected):
        await billing(db).handle(event(app_user_id=uuid.uuid4()))

    (rejected,) = await audited(db, AuditEventType.WEBHOOK_REJECTED)
    assert rejected.context["reason"] == "unknown_account"


async def test_an_app_user_id_that_is_not_a_uuid_is_refused(db):
    """RevenueCat will happily carry whatever the client set.

    An anonymous `$RCAnonymousID:...` is the common one — it means the purchase
    was made before sign-in, which is a real situation and not one to guess an
    owner for.
    """
    with pytest.raises(WebhookRejected):
        await billing(db).handle(event(app_user_id="$RCAnonymousID:87c6049c"))

    (rejected,) = await audited(db, AuditEventType.WEBHOOK_REJECTED)
    assert rejected.context["reason"] == "unattributable"


# --- Provenance -----------------------------------------------------------


async def test_every_entry_a_purchase_writes_is_attributed_to_the_store(db, account):
    """`WEBHOOK`, never `USER` (`CLAUDE.md` → Audit model).

    There is no caller here. An entry attributed to the account holder reads as
    something they did in the app, and *"who moved this balance"* is the first
    question asked of a balance nobody can explain.
    """
    await billing(db).handle(event(app_user_id=account.user_id))

    assert {entry.actor for entry in await entries(db, account.user_id)} == {"webhook"}


async def test_an_entitlement_change_is_provable_afterwards(db, account):
    """The audit row that explains a tier, which the ledger cannot.

    `ledger_entries` records the minutes and says nothing about the plan behind
    them, and CLAUDE.md forbids mirroring money into `audit_events` — so this row
    carries the entitlement and no balance.
    """
    await billing(db).handle(event(app_user_id=account.user_id))

    (changed,) = await audited(db, AuditEventType.ENTITLEMENT_CHANGED)
    assert changed.user_id == account.user_id
    assert changed.context["tier"] == "pro"
    assert changed.context["previous_tier"] == "free"


async def test_a_lazy_reset_and_a_late_renewal_leave_one_allowance(db, account, ledger):
    """Both paths can run for the same renewal, and often will.

    The reset is lazy — a user who opens the app on the morning their period
    rolls gets repaired by `ensure_current_period` before RevenueCat's `RENEWAL`
    has arrived. Then it arrives.

    The two do **not** interlock on the idempotency key: they compute different
    boundaries (a flat thirty days against the store's real expiry), so they
    advance to different `period_id`s and neither refuses the other's write. What
    keeps this correct is the expire-then-grant pair — the second pass writes off
    whatever the first granted before granting again — so the user ends with one
    allowance rather than two.

    Written after a surviving mutation showed the interlock this was documented
    to have does not exist. The behaviour is right; the explanation was not.
    """
    yesterday = datetime.now(UTC) - timedelta(days=1)
    await billing(db).handle(event(app_user_id=account.user_id, expires=yesterday))

    # The user opens the app before the store's callback lands.
    await ledger.ensure_current_period(user_id=account.user_id)
    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == (
        MONTHLY_ALLOWANCE_SECONDS["pro"]
    )

    renewed = datetime.now(UTC) + timedelta(days=29)
    await billing(db).handle(
        event(app_user_id=account.user_id, type="RENEWAL", expires=renewed)
    )

    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == (
        MONTHLY_ALLOWANCE_SECONDS["pro"]
    )
    await db.refresh(account)
    assert abs((account.period_ends_at - renewed).total_seconds()) < 2
