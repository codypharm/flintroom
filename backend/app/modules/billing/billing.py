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

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.errors import WebhookRejected, WebhookUnconfigured
from app.core.logging import get_logger
from app.modules.audit_log.schemas import AuditEventType
from app.modules.audit_log.service import AuditService
from app.modules.billing.revenuecat import RevenueCatEvent, parsed, verify

log = get_logger(__name__, tag="billing")

#: Event types this handler acts on. Everything else RevenueCat sends —
#: paywall impressions, experiment enrolments, alias changes — is acknowledged
#: and ignored, because a non-200 buys five retries each over two and a half
#: hours for something we were never going to do anything about.
#:
#: Empty in this slice: the wall is built before anything is put behind it, and
#: the entitlement and top-up handling is the next one. Deliberately a named
#: constant already, so that adding a handler is adding a name here rather than
#: an `if` somewhere in a dispatch.
HANDLED_EVENT_TYPES: frozenset[str] = frozenset()


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

        await self._handle(event)

    async def _reject(self, reason: str = "unknown", **context: object) -> None:
        """One durable row per refused callback.

        No `user_id`: an unverified body's idea of who it is about is not
        evidence of anything, and attaching it would let a forger write rows
        against somebody else's account.
        """
        await self._audit.record(
            AuditEventType.WEBHOOK_REJECTED, provider="revenuecat", reason=reason, **context
        )

    async def _handle(self, event: RevenueCatEvent) -> None:
        """Act on an event that is genuinely from the store.

        Unhandled types are logged rather than audited. An audit row is for
        something worth proving later, and *"a paywall was shown"* is neither a
        state change nor a security event — recording every one would bury the
        rejections in the same table.
        """
        if event.type not in HANDLED_EVENT_TYPES:
            log.info(
                "webhook_event_ignored",
                provider="revenuecat",
                event_type=event.type,
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

        # No handled types yet — the wall ships before what stands behind it.
        raise NotImplementedError(event.type)  # pragma: no cover


def _json(body: bytes) -> object:
    """The body as data, or the same refusal every other malformed callback gets.

    A `JSONDecodeError` reaching the handler would be a 500, and RevenueCat
    retries a 500 five times against a body that will never parse.
    """
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WebhookRejected(reason="unreadable_payload") from exc
