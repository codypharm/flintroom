"""The wall in front of the money.

A webhook is the one endpoint an attacker can reach that grants minutes, and it
authenticates with a shared secret rather than a user's credential — so it is
worth more to forge than anything else in the API. `CLAUDE.md` fixes the rule:
*"Signature verified before payload parsed. Unverified = reject + audit log."*

Two properties do all the work and both are easy to lose in a refactor:

- The signature is checked against the **raw bytes**. Re-serializing parsed JSON
  produces different bytes and a verification that cannot pass — so a future
  handler that takes a Pydantic body instead of a `Request` breaks this
  permanently, and it breaks *open* if anyone then relaxes the check to make it
  work again.
- An unverified payload is **never acted on**, and the rejection is a durable
  row rather than a log line, because a burst of them is the only warning that
  somebody is trying.

This slice is the wall alone. Nothing here grants anything yet: entitlements and
top-ups are the next one, and putting them behind an unproven wall is the order
this codebase does not build in.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from sqlalchemy import select

from app.modules.audit_log.models import AuditEvent
from app.modules.audit_log.schemas import AuditEventType
from tests.conftest import WEBHOOK_SECRET as SECRET

PURCHASE = {
    "api_version": "1.0",
    "event": {
        "id": "01234567-89ab-cdef-0123-456789abcdef",
        "type": "INITIAL_PURCHASE",
        "event_timestamp_ms": 1_755_000_000_000,
        "app_user_id": "0f8fad5b-d9cb-469f-a165-70867728950e",
        "product_id": "flintroom_pro_monthly",
        "entitlement_ids": ["pro"],
        "purchased_at_ms": 1_755_000_000_000,
        "expiration_at_ms": 1_757_592_000_000,
        "period_type": "NORMAL",
        "store": "APP_STORE",
        "environment": "PRODUCTION",
    },
}


def signed(body: bytes, *, secret: str = SECRET, at: int | None = None) -> dict[str, str]:
    """The header RevenueCat sends: `t=<unix>,v1=<hmac of "t.body">`."""
    timestamp = str(at if at is not None else int(time.time()))
    digest = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return {
        "X-RevenueCat-Webhook-Signature": f"t={timestamp},v1={digest}",
        "Content-Type": "application/json",
    }


def payload(event: dict | None = None) -> bytes:
    """Serialized once, so the exact bytes are what gets signed and sent."""
    return json.dumps(event if event is not None else PURCHASE).encode()


async def rejections(db) -> list[AuditEvent]:
    rows = await db.scalars(
        select(AuditEvent).where(
            AuditEvent.event_type == AuditEventType.WEBHOOK_REJECTED.value
        )
    )
    return list(rows)


async def test_a_properly_signed_event_is_accepted(client, db, account):
    """The tracer bullet: over the wall and all the way to a tier.

    Against a real account rather than the fixture's invented id, so this proves
    the whole path rather than only the signature — what the handler then does
    with it is `test_revenuecat_entitlements.py`.

    200 specifically: anything else is retried five times over roughly two and a
    half hours, so a handler that answers 500 to something it merely does not
    recognise turns one unknown event into five.
    """
    body = payload(
        {
            "api_version": "1.0",
            "event": {**PURCHASE["event"], "app_user_id": str(account.user_id)},
        }
    )

    accepted = await client.post(
        "/v1/webhooks/revenuecat", content=body, headers=signed(body)
    )

    assert accepted.status_code == 200, accepted.text
    assert await rejections(db) == []

    await db.refresh(account)
    assert account.entitlement_tier == "pro"


async def test_a_forged_signature_is_refused_and_recorded(client, db):
    """The whole point. A body somebody else signed grants nothing.

    Recorded durably rather than logged, because one of these is noise and forty
    in a minute is somebody working through a wordlist — and application logs may
    be sampled or rotated away, which is exactly what `CLAUDE.md` says the audit
    trail may not be.
    """
    body = payload()

    refused = await client.post(
        "/v1/webhooks/revenuecat",
        content=body,
        headers=signed(body, secret="a-secret-that-is-not-ours"),
    )

    assert refused.status_code == 400
    (rejected,) = await rejections(db)
    assert rejected.context["reason"] == "bad_signature"


async def test_an_unsigned_request_is_refused(client, db):
    """No header at all — the first thing anybody tries."""
    refused = await client.post(
        "/v1/webhooks/revenuecat",
        content=payload(),
        headers={"Content-Type": "application/json"},
    )

    assert refused.status_code == 400
    (rejected,) = await rejections(db)
    assert rejected.context["reason"] == "missing_signature"


@pytest.mark.parametrize(
    "header",
    [
        "nonsense",
        "t=,v1=",
        "v1=deadbeef",
        "t=1755000000",
        "t=not-a-number,v1=deadbeef",
    ],
)
async def test_a_malformed_signature_header_is_refused(client, db, header):
    """Parsed defensively, because this string is attacker-controlled.

    A parser that raises on a missing `=` turns a hostile header into a 500 —
    which is a different answer from a 400 and tells whoever is probing that they
    found something. Every shape here is a refusal, not a traceback.
    """
    refused = await client.post(
        "/v1/webhooks/revenuecat",
        content=payload(),
        headers={
            "X-RevenueCat-Webhook-Signature": header,
            "Content-Type": "application/json",
        },
    )

    assert refused.status_code == 400
    assert len(await rejections(db)) == 1


async def test_a_replayed_signature_from_last_week_is_refused(client, db):
    """The timestamp is in the signature so that an old one cannot be reused.

    Without a tolerance, a request captured once is valid forever: the body and
    header together stay a perfectly good signed message, and replaying it
    replays whatever it granted.
    """
    body = payload()

    refused = await client.post(
        "/v1/webhooks/revenuecat",
        content=body,
        headers=signed(body, at=int(time.time()) - 7 * 24 * 3600),
    )

    assert refused.status_code == 400
    (rejected,) = await rejections(db)
    assert rejected.context["reason"] == "stale_signature"


async def test_a_signature_over_different_bytes_is_refused(client, db):
    """Signed correctly, for a different body — the substitution attack.

    The one a re-serializing handler lets through: parse the JSON, verify
    against `json.dumps` of the result, and any two bodies that parse the same
    become interchangeable.
    """
    headers = signed(payload())
    tampered = dict(PURCHASE)
    tampered["event"] = {**PURCHASE["event"], "product_id": "flintroom_teams_monthly"}

    refused = await client.post(
        "/v1/webhooks/revenuecat", content=payload(tampered), headers=headers
    )

    assert refused.status_code == 400
    (rejected,) = await rejections(db)
    assert rejected.context["reason"] == "bad_signature"


async def test_a_deployment_with_no_secret_configured_refuses_everything(
    client_without_webhook_secret, db
):
    """Deny by default (`CLAUDE.md`), and the failure mode decides it.

    An unconfigured secret that accepted everything would be an open endpoint
    that grants minutes, and it would look completely healthy — a 200 to every
    caller, no errors, nothing to notice. Refusing instead breaks purchases
    loudly on a deployment that forgot a variable, which is the direction to
    fail in.
    """
    body = payload()

    refused = await client_without_webhook_secret.post(
        "/v1/webhooks/revenuecat", content=body, headers=signed(body)
    )

    assert refused.status_code == 503
    (rejected,) = await rejections(db)
    assert rejected.context["reason"] == "unconfigured"


async def test_a_body_that_is_not_the_shape_we_expect_is_refused(client, db):
    """Signed by RevenueCat and still not something to act on.

    A 400 rather than a 422 because there is no user to correct it and no client
    to re-send it — and it must not be a 500, which RevenueCat would retry five
    times against a body that will never parse.
    """
    body = json.dumps({"api_version": "1.0", "event": {"type": "INITIAL_PURCHASE"}}).encode()

    refused = await client.post(
        "/v1/webhooks/revenuecat", content=body, headers=signed(body)
    )

    assert refused.status_code == 400


async def test_an_event_we_do_not_handle_is_acknowledged_rather_than_retried(client, db):
    """RevenueCat sends paywall impressions and experiment enrolments too.

    Answering anything but 200 to those buys five retries each, on a schedule
    that runs for two and a half hours, for an event we were never going to act
    on. Acknowledged and recorded is the correct answer.
    """
    unhandled = {
        "api_version": "1.0",
        "event": {**PURCHASE["event"], "type": "PAYWALL_IMPRESSION"},
    }
    body = payload(unhandled)

    accepted = await client.post(
        "/v1/webhooks/revenuecat", content=body, headers=signed(body)
    )

    assert accepted.status_code == 200
    assert await rejections(db) == []


async def test_a_test_event_from_the_dashboard_is_accepted(client):
    """The button in the RevenueCat dashboard, which is how anybody checks this.

    Worth its own test because it is the first request this endpoint will ever
    receive in production, and a rejection there reads as "the integration is
    broken" when the wall is in fact working.
    """
    body = payload({"api_version": "1.0", "event": {**PURCHASE["event"], "type": "TEST"}})

    accepted = await client.post(
        "/v1/webhooks/revenuecat", content=body, headers=signed(body)
    )

    assert accepted.status_code == 200
