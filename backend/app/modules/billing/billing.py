"""What a store's callback does to an account.

Separate from `LedgerService`, which owns seconds and buckets and is written to
by the tick loop, the reaper and the API. This owns the other direction: what
arrives from outside, whether to believe it, and what it means.

The split matters for provenance. Every write here is attributed to `WEBHOOK`,
because there is no caller — a purchase credited under the account holder reads
as something they did in the app, and "who moved this balance" is the first
question asked of a balance nobody can explain.

Vendor shapes stay in `revenuecat.py`. This module deals in events that have
already been proven genuine.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.errors import WebhookRejected, WebhookUnconfigured
from app.core.logging import get_logger
from app.modules.audit_log.schemas import AuditEventType
from app.modules.audit_log.service import AuditService
from app.modules.billing.models import Account
from app.modules.billing.revenuecat import RevenueCatEvent, parsed, verify
from app.modules.billing.service import LedgerService
from app.modules.billing.tiers import (
    FREE_TIER,
    SUBSCRIPTION_TIERS,
    TOPUP_SECONDS,
)

log = get_logger(__name__, tag="billing")

#: Types that move an account onto a plan. All three carry the product and the
#: expiry, and are the same write with different provenance.
SUBSCRIPTION_EVENTS = frozenset(
    {"INITIAL_PURCHASE", "RENEWAL", "PRODUCT_CHANGE", "UNCANCELLATION"}
)

#: Types that end one. `CANCELLATION` is deliberately absent — see `_cancel`.
REVOCATION_EVENTS = frozenset({"EXPIRATION"})

#: The consumable packs in §4.5.
TOPUP_EVENTS = frozenset({"NON_RENEWING_PURCHASE"})

#: Why a `CANCELLATION` revokes rather than merely stopping renewal.
#:
#: RevenueCat reports a refund as a cancellation, and `cancel_reason` is the only
#: thing separating *"I will not renew"* from *"give me my money back"*. Treating
#: them alike either takes a paid month from somebody who cancelled, or leaves a
#: refunded user on a paid tier.
REFUND_CANCEL_REASONS = frozenset({"CUSTOMER_SUPPORT"})

#: Everything this handler acts on. Anything else RevenueCat sends — paywall
#: impressions, experiment enrolments, alias changes — is acknowledged and
#: ignored, because a non-200 buys five retries each over two and a half hours
#: for something we were never going to do anything about.
HANDLED_EVENT_TYPES: frozenset[str] = (
    SUBSCRIPTION_EVENTS | REVOCATION_EVENTS | TOPUP_EVENTS | {"CANCELLATION"}
)

#: Periods that are not paid for, and so grant nothing — #109.
#:
#: `TRIAL` is a free trial and `INTRO` an introductory-price offer; both are
#: attached to a product from the store console with no code change here, and
#: both arrive as an ordinary `INITIAL_PURCHASE` distinguished only by this
#: field. `NORMAL`, and an absent value from a store that does not send one,
#: are paid and grant.
TRIAL_PERIODS = frozenset({"TRIAL", "INTRO"})


class BillingService:
    """The only path through which a store's callback reaches an account."""

    def __init__(self, db: AsyncSession, actor: ActorContext | None = None) -> None:
        self._db = db
        self._actor = actor or ActorContext.system()
        self._audit = AuditService(db, self._actor, tag="billing")

    async def receive_revenuecat(
        self, *, body: bytes, signature: str | None, secret: str | None
    ) -> None:
        """Verify a callback, then act on it. In that order, always.

        The order is the security property. `body` is the raw request bytes and
        nothing is parsed from them until the signature over those exact bytes
        has been checked — re-serializing parsed JSON makes any two bodies that
        parse the same interchangeable, and the check quietly stops meaning
        anything.

        Every refusal is recorded before it is raised. One is noise; a burst is
        the only warning anyone gets that somebody is working on the secret, and
        `CLAUDE.md` puts that in `audit_events` rather than a log line precisely
        because logs may be sampled and these may not.
        """
        if secret is None:
            await self._reject("unconfigured")
            raise WebhookUnconfigured()

        try:
            verify(body, signature, secret=secret)
            event = parsed(_json(body)).event
        except WebhookRejected as refused:
            await self._reject(**refused.context)
            raise

        await self.handle(event)

    async def _reject(self, reason: str = "unknown", **context: Any) -> None:
        """One durable row per refused callback.

        No `user_id`: an unverified body's idea of who it is about is not
        evidence of anything, and attaching it would let a forger write rows
        against somebody else's account.

        `**context: Any` rather than `object`, for the reason `Settings.__init__`
        gives: these are forwarded untouched to a method with typed keyword
        parameters, and nothing here inspects them. `object` was stricter and
        also untrue.
        """
        await self._audit.record(
            AuditEventType.WEBHOOK_REJECTED, provider="revenuecat", reason=reason, **context
        )

    async def handle(self, event: RevenueCatEvent) -> None:
        """Act on an event that is genuinely from the store.

        Public because the verification and the meaning are different jobs and
        the tests for each should not have to perform the other: everything here
        assumes the signature already passed.

        Unhandled types are logged rather than audited. An audit row is for
        something worth proving later, and *"a paywall was shown"* is neither a
        state change nor a security event — recording every one would bury the
        rejections in the same table.
        """
        if event.type not in HANDLED_EVENT_TYPES:
            log.info(
                "webhook_event_ignored",
                provider="revenuecat",
                store_event=event.type,
                event_id=event.id,
                # Carried on the ignored path specifically, because that is where
                # every event lands until the handlers exist — and these three
                # are what the handlers will need to be written against. A store
                # identifier is whatever was typed into App Store Connect, and
                # Play may return a base-plan suffix we did not choose, so the
                # only reliable source is an event that actually arrived.
                product_id=event.product_id,
                entitlement_ids=event.entitlement_ids,
                environment=event.environment,
            )
            return

        # Sandbox before anything else, because everything below it grants. A
        # licence tester buys every product without being charged and the event
        # is otherwise identical to a real one — `environment` is the only thing
        # telling them apart, so a handler that checks it late is one refactor
        # from minting minutes for free.
        if event.environment and event.environment.upper() != "PRODUCTION":
            await self._reject(
                "sandbox_purchase",
                store_event=event.type,
                environment=event.environment,
            )
            raise WebhookRejected(reason="sandbox_purchase")

        # A trial, for the same reason and in the same place: everything below
        # this grants, and `period_type` is the only thing separating a
        # subscription somebody paid for from one they have not.
        #
        # **This is a guard against a checkbox, not against a user.** #109
        # records the decision that no free trial is ever configured — the app
        # already grants fifteen minutes at signup, which is one complete room,
        # and a Play trial would stack a second and far costlier free tier on
        # top of it. Play can attach a trial offer to a product from the console
        # with no code change here, so without this the leak opens silently and
        # nothing raises.
        #
        # It therefore fires only on a misconfiguration, and the audit row is an
        # alarm rather than an explanation to anybody. That is also why refusing
        # outright is acceptable: a trial subscriber left with an active
        # subscription and no minutes would be poor treatment of a real user,
        # and there is not supposed to be one. If a trial is ever genuinely
        # wanted, this is replaced by a policy — most likely granting the
        # free-tier fifteen minutes — rather than deleted.
        #
        # An expiry or cancellation carrying `TRIAL` is refused too, harmlessly:
        # nothing was granted, so there is nothing to take back.
        if event.period_type and event.period_type.upper() in TRIAL_PERIODS:
            await self._reject(
                "trial_period",
                store_event=event.type,
                period_type=event.period_type,
                product_id=event.product_id,
            )
            raise WebhookRejected(reason="trial_period")

        user_id = await self._account_of(event)

        try:
            if event.type in TOPUP_EVENTS:
                await self._grant_topup(user_id, event)
            elif event.type in REVOCATION_EVENTS:
                await self._apply_tier(user_id, FREE_TIER, None, event)
            elif event.type == "CANCELLATION":
                await self._cancel(user_id, event)
            else:
                await self._apply_tier(
                    user_id, self._tier_of(event), _expiry(event), event
                )
        except _UnknownProduct as unknown:
            # The audit row carries the identifier that actually arrived, which
            # is the entire correction when the names chosen in
            # `docs/billing-setup.md` and the store's disagree. Refused rather
            # than granted-nothing-quietly: the quiet version looks exactly like
            # a working integration while selling minutes nobody receives.
            await self._reject(
                "unknown_product",
                store_event=event.type,
                event_id=event.id,
                product_id=unknown.event.product_id,
            )
            raise WebhookRejected(reason="unknown_product") from unknown

    async def _cancel(self, user_id: uuid.UUID, event: RevenueCatEvent) -> None:
        """Auto-renew off is not access off, and the difference is a month.

        A cancellation fires when somebody turns off renewal — they have paid
        through the end of the period and are entitled to every minute of it.
        Revoking here would take back time already bought, from a user who has
        just signalled they are wavering, which is the worst available moment.

        A refund is the exception and arrives under the same type. The period
        boundary already on the account is what ends an ordinary cancellation:
        `ensure_current_period` grants nothing to a tier with no monthly
        allowance, so a lapsed subscriber simply stops being topped up.
        """
        if event.cancel_reason in REFUND_CANCEL_REASONS:
            await self._apply_tier(user_id, FREE_TIER, None, event)
            return

        log.info(
            "subscription_cancellation_noted",
            user_id=str(user_id),
            event_id=event.id,
            cancel_reason=event.cancel_reason,
        )

    async def _apply_tier(
        self,
        user_id: uuid.UUID,
        tier: str,
        period_ends_at: datetime | None,
        event: RevenueCatEvent,
    ) -> None:
        """Move the account, and leave a row that explains why it moved.

        The audit row carries the entitlement and no balance. `ledger_entries`
        is the money record and CLAUDE.md forbids mirroring a movement into
        `audit_events` — but the ledger cannot say *which plan* those minutes
        came from, and that is the question asked of a tier nobody recognises.
        """
        previous, _ = await LedgerService(self._db, self._actor).apply_subscription(
            user_id=user_id, tier=tier, period_ends_at=period_ends_at
        )

        if previous != tier:
            await self._audit.record(
                AuditEventType.ENTITLEMENT_CHANGED,
                user_id=user_id,
                tier=tier,
                previous_tier=previous,
                provider="revenuecat",
                store_event=event.type,
                event_id=event.id,
                product_id=event.product_id,
            )

    async def _grant_topup(self, user_id: uuid.UUID, event: RevenueCatEvent) -> None:
        """A consumable pack, into the bucket that never expires.

        Idempotent on the event id, because unlike a subscription there is no
        period to key on — a duplicate delivery has nothing else distinguishing
        it from a second purchase, and §4.5 explicitly expects the same pack to
        be bought more than once.
        """
        seconds = TOPUP_SECONDS.get(event.product_id or "")
        if seconds is None:
            raise _UnknownProduct(event)

        granted = await LedgerService(self._db, self._actor).grant_topup(
            user_id=user_id, seconds=seconds, idempotency_key=f"revenuecat:{event.id}"
        )
        if not granted:
            return

        await self._audit.record(
            AuditEventType.TOPUP_PURCHASED,
            user_id=user_id,
            provider="revenuecat",
            product_id=event.product_id,
            event_id=event.id,
            seconds=seconds,
        )

    def _tier_of(self, event: RevenueCatEvent) -> str:
        """The tier this product sells, or a refusal naming what arrived."""
        tier = SUBSCRIPTION_TIERS.get(event.product_id or "")
        if tier is None:
            raise _UnknownProduct(event)
        return tier

    async def _account_of(self, event: RevenueCatEvent) -> uuid.UUID:
        """Whose purchase this is, or a refusal rather than a guess.

        `app_user_id` is our own `user_id`, set by the client. Two ways it is
        not: a purchase made before sign-in carries RevenueCat's anonymous id,
        and anything else is a client bug. Creating an account here would let
        whoever can forge a signed event populate our user table, and a real
        purchase we cannot attribute deserves somebody's attention rather than a
        silent no-op.
        """
        try:
            user_id = uuid.UUID(event.app_user_id)
        except ValueError:
            await self._reject(
                "unattributable", store_event=event.type, event_id=event.id
            )
            raise WebhookRejected(reason="unattributable") from None

        exists = await self._db.scalar(
            select(Account.user_id).where(Account.user_id == user_id)
        )
        if exists is None:
            await self._reject(
                "unknown_account", store_event=event.type, event_id=event.id
            )
            raise WebhookRejected(reason="unknown_account")

        return user_id


class _UnknownProduct(Exception):
    """A product identifier absent from `billing/tiers.py`.

    Internal, and converted to a refusal with an audit row by `receive`. Its own
    type rather than a `WebhookRejected` raised directly, so the audit row can
    carry the identifier that arrived — which is the whole correction when the
    chosen names and the store's disagree.
    """

    def __init__(self, event: RevenueCatEvent) -> None:
        self.event = event
        super().__init__(event.product_id or "")


def _expiry(event: RevenueCatEvent) -> datetime | None:
    """The store's period boundary, which replaces our 30-day placeholder."""
    if event.expiration_at_ms is None:
        return None
    return datetime.fromtimestamp(event.expiration_at_ms / 1000, tz=UTC)


def _json(body: bytes) -> object:
    """The body as data, or the same refusal every other malformed callback gets.

    A `JSONDecodeError` reaching the handler would be a 500, and RevenueCat
    retries a 500 five times against a body that will never parse.
    """
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WebhookRejected(reason="unreadable_payload") from exc
