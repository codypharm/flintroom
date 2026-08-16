"""RevenueCat's half of the billing contract.

Everything vendor-shaped stops here: the signature scheme, the header format, the
event names, the payload fields. The rest of billing deals in tiers and seconds
and has never heard of a store.

**Verification is a pure function over bytes**, deliberately. It takes the raw
body and the raw header and returns nothing — no request object, no session, no
settings. That is what makes the one security property this module exists for
testable without a server, and what stops it drifting into a handler where the
body has already been parsed.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.errors import WebhookRejected

#: What RevenueCat signs with, and where it puts it.
SIGNATURE_HEADER = "X-RevenueCat-Webhook-Signature"

#: How far out of date a signature may be, in seconds.
#:
#: The timestamp is inside the signed material precisely so a captured request
#: cannot be replayed forever — without a bound, one intercepted body and header
#: stay a valid signed message for all time, and replaying it replays whatever it
#: granted.
#:
#: Five minutes is RevenueCat's own suggested tolerance. It has to cover clock
#: skew between their machines and ours, and their retry schedule does not
#: threaten it: a retry is a fresh request with a fresh signature, not a
#: rebroadcast of the old one.
SIGNATURE_TOLERANCE_SECONDS = 5 * 60


def verify(body: bytes, header: str | None, *, secret: str) -> None:
    """Prove this body came from RevenueCat, or raise.

    The HMAC covers `"{timestamp}.{body}"` — the timestamp is inside the signed
    material, which is what stops it being edited to defeat the freshness check.

    `body` is the **raw request bytes** and nothing else will do. Verifying
    against a re-serialization of parsed JSON makes any two bodies that parse the
    same interchangeable, so an attacker may reorder keys, change whitespace, or
    swap a value the parser coerces — and the signature still matches.

    Ordered cheapest-first, and every failure is the same refusal to the sender
    with a different `reason` in the audit row. The distinction is ours: a bad
    signature is somebody trying, a stale one is usually a clock.
    """
    if not header:
        raise WebhookRejected(reason="missing_signature")

    timestamp, signature = _parts(header)

    if abs(time.time() - timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        raise WebhookRejected(reason="stale_signature", signed_at=timestamp)

    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()

    # Constant time, because a comparison that returns early on the first
    # differing byte leaks how much of a guess was right — which is enough to
    # find the rest one byte at a time.
    if not hmac.compare_digest(expected, signature):
        raise WebhookRejected(reason="bad_signature")


def _parts(header: str) -> tuple[int, str]:
    """`t=<unix>,v1=<hex>`, parsed without trusting any of it.

    This string is attacker-controlled, so every shape of nonsense has to be a
    refusal rather than an exception: a `split("=")` that unpacks two values
    turns a header with one `=` into a 500, and a 500 tells whoever is probing
    that they found the edge of something.
    """
    fields: dict[str, str] = {}
    for part in header.split(","):
        name, _, value = part.partition("=")
        fields[name.strip()] = value.strip()

    try:
        timestamp = int(fields["t"])
        signature = fields["v1"]
    except (KeyError, ValueError) as exc:
        raise WebhookRejected(reason="malformed_signature") from exc

    if not signature:
        raise WebhookRejected(reason="malformed_signature")

    return timestamp, signature


class RevenueCatEvent(BaseModel):
    """One event, narrowed to the fields billing acts on.

    Deliberately permissive about everything else: RevenueCat adds fields, and a
    schema that refused unknown ones would start rejecting valid callbacks on
    their release schedule rather than ours. That is the opposite of the rule
    applied to *our* clients, where `extra="forbid"` catches a misspelled field
    before it becomes a silently ignored one — here the sender is not ours to
    correct, and refusing costs five retries and a missed purchase.

    `type` is a plain string rather than an enum for the same reason. An unknown
    type is acknowledged and recorded, never an error: this endpoint also
    receives paywall impressions and experiment enrolments, and answering
    anything but 200 to those buys five retries each.
    """

    model_config = ConfigDict(extra="ignore")

    #: RevenueCat's own id for this event, and the idempotency key for anything
    #: it grants. Retries carry the same one, which is what makes five deliveries
    #: of a purchase one grant.
    id: str = Field(min_length=1, max_length=128)

    type: str = Field(min_length=1, max_length=64)

    #: Our `user_id`, because the app identifies the customer to RevenueCat with
    #: it. A value that is not one of our ids is a purchase we cannot attribute,
    #: which is a thing to notice rather than to guess at.
    app_user_id: str = Field(min_length=1, max_length=128)

    event_timestamp_ms: int | None = None
    product_id: str | None = Field(default=None, max_length=128)
    entitlement_ids: list[str] | None = None
    purchased_at_ms: int | None = None
    expiration_at_ms: int | None = None
    period_type: str | None = Field(default=None, max_length=32)
    store: str | None = Field(default=None, max_length=32)

    #: `PRODUCTION` or `SANDBOX`. Carried because a sandbox purchase must never
    #: grant real minutes, and the two are otherwise identical.
    environment: str | None = Field(default=None, max_length=32)

    cancel_reason: str | None = Field(default=None, max_length=64)
    expiration_reason: str | None = Field(default=None, max_length=64)


class RevenueCatNotification(BaseModel):
    """The envelope. One event per delivery."""

    model_config = ConfigDict(extra="ignore")

    api_version: Literal["1.0"] | str = "1.0"
    event: RevenueCatEvent


def parsed(payload: Any) -> RevenueCatNotification:
    """The notification, or a refusal that will not be retried into a loop.

    A body RevenueCat signed and we cannot read is not a 500: there is no user to
    correct it and no client to re-send it, and a 5xx buys five retries against a
    payload that will never parse. It is recorded and refused once.
    """
    try:
        return RevenueCatNotification.model_validate(payload)
    except ValidationError as exc:
        # Narrow on purpose. Catching `Exception` here would turn a bug in this
        # module into a tidy 400 that RevenueCat accepts and nobody investigates
        # — which is exactly the "dressing a crash up as a 4xx" CLAUDE.md
        # forbids. A real fault stays a 500 with a traceback.
        raise WebhookRejected(reason="unreadable_payload") from exc
