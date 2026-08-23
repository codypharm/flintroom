"""The email seam — an interface, then Resend behind it. Task #101.

The contract is "send this message"; the vendor is a sibling adapter, exactly
the split `core/storage.py` draws. One consumer exists and only one was
built for: the account-deletion confirmation. Everything else this could
carry — receipts (the store's job), balance nags (the rationing pressure the
product refuses) — was checked and declined before a line was written.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.core.email_resend import ResendEmailSender, build_email_sender

pytestmark = pytest.mark.asyncio


def sender_over(handler) -> tuple[ResendEmailSender, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return (
        ResendEmailSender(
            http, api_key="a-resend-key", sender="Flintroom <hello@flintroom.app>"
        ),
        seen,
    )


async def test_a_message_becomes_one_authenticated_resend_call():
    sender, seen = sender_over(
        lambda request: httpx.Response(200, json={"id": "re_1"})
    )

    await sender.send(
        to="presenter@example.com",
        subject="Your account is scheduled for deletion",
        text="Everything will be destroyed on 31 August 2026.",
    )

    [request] = seen
    assert str(request.url) == "https://api.resend.com/emails"
    assert request.headers["authorization"] == "Bearer a-resend-key"
    body = json.loads(request.content)
    assert body == {
        "from": "Flintroom <hello@flintroom.app>",
        "to": ["presenter@example.com"],
        "subject": "Your account is scheduled for deletion",
        "text": "Everything will be destroyed on 31 August 2026.",
    }


async def test_a_refusal_from_the_vendor_is_an_error_the_caller_can_absorb():
    """The adapter raises; the *caller* decides that a lost email must not
    fail the thing it confirms. Swallowing here would make every send look
    successful to whoever is deciding whether to log a failure."""
    sender, _ = sender_over(
        lambda request: httpx.Response(422, json={"message": "no"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await sender.send(to="a@b.c", subject="s", text="t")


def _settings(**overrides) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x:y@localhost/flintroom",
        jwt_secret="a-test-signing-key-of-sufficient-length",
        google_client_id="test.apps.googleusercontent.com",
        apple_client_id="com.flintroom.test",
        **overrides,
    )


def test_a_deployment_without_the_pair_sends_nothing():
    """Both or neither, like the object store: a key with no from-address
    would send mail Resend rejects for an unverified sender, surfacing at the
    one moment somebody is deleting their account rather than at boot."""
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))

    assert build_email_sender(_settings(), http) is None
    assert (
        build_email_sender(_settings(resend_api_key="key"), http) is None
    )
    assert (
        build_email_sender(
            _settings(email_from="Flintroom <hello@flintroom.app>"), http
        )
        is None
    )


def test_a_configured_deployment_gets_the_resend_adapter():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))

    built = build_email_sender(
        _settings(
            resend_api_key="key", email_from="Flintroom <hello@flintroom.app>"
        ),
        http,
    )

    assert isinstance(built, ResendEmailSender)
