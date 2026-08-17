"""How errors reach the client.

One handler owns the translation. A router that catches and re-raises its own
HTTPExceptions is a router that will eventually disagree with another one about
what a missing account is.
"""

import logging

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.errors import (
    AccountNotFound,
    ActiveSessionExists,
    FlintroomError,
    ProviderUnavailable,
)
from app.main import create_app


@pytest.fixture
def app():
    app = create_app()

    @app.get("/boom/{kind}")
    async def boom(kind: str):  # pragma: no cover - exercised via the client
        if kind == "missing":
            raise AccountNotFound(user_id="u-1")
        if kind == "conflict":
            raise ActiveSessionExists(user_id="u-1", existing_session_id="s-1")
        if kind == "provider":
            raise ProviderUnavailable(provider="elevenlabs", operation="start_agent")
        raise RuntimeError("a genuine bug nobody anticipated")

    return app


@pytest.fixture
async def client(app):
    # Starlette builds the 500 response *and* re-raises so the server can log
    # the traceback. Under uvicorn the client still receives the response; the
    # test transport would re-raise instead of returning it, so opt out here to
    # observe what a real caller would see.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_a_known_error_becomes_its_declared_status_and_payload(client):
    response = await client.get("/boom/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "account_not_found", "message": "No ledger account for this user."}
    }


async def test_a_duplicate_action_is_a_conflict_not_a_500(client):
    """CLAUDE.md is explicit that a duplicate action is never a 500."""
    response = await client.get("/boom/conflict")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "active_session_exists"


async def test_a_provider_failure_is_502_and_names_no_vendor(client):
    """The user does not need to know which vendor broke.

    Naming it exposes internal architecture and means the message goes stale the
    moment the voice provider is swapped — which the stack is explicitly built
    to allow.
    """
    response = await client.get("/boom/provider")

    assert response.status_code == 502
    assert "elevenlabs" not in response.text.lower()


async def test_an_unexpected_exception_stays_a_500_and_leaks_nothing(client, caplog):
    """A real bug must not be dressed up as a tidy 4xx.

    It also must not echo its message: exception text routinely contains query
    fragments, paths and identifiers.
    """
    with caplog.at_level(logging.ERROR):
        response = await client.get("/boom/unexpected")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Something went wrong."}
    }
    assert "a genuine bug nobody anticipated" not in response.text

    # ...but it is fully logged, with the traceback, or it is undebuggable.
    assert any(record.exc_info for record in caplog.records)


async def test_a_handled_error_is_logged_with_its_context(client, caplog):
    """The context that explains the failure reaches the log, not the client."""
    with caplog.at_level(logging.WARNING):
        await client.get("/boom/conflict")

    record = next(r for r in caplog.records if getattr(r, "tag", None) == "http")
    assert record.context["user_id"] == "u-1"
    assert record.context["existing_session_id"] == "s-1"
    assert record.context["status_code"] == 409


def test_no_error_message_anywhere_names_a_vendor():
    """The guarantee, held once, in the only place it can be held.

    `CLAUDE.md` forbids naming a provider to a client: it exposes internal
    architecture to whoever is probing, and it goes stale the moment the vendor
    is swapped — which the seams throughout this project exist to permit.

    Three adapter tests used to assert this each for themselves, in the shape
    `assert "gemini" not in raised.value.message.lower()`. Every one of them was
    vacuous. `message` is a class attribute, so the assertion passed no matter
    what the adapter did — proven when a mutation putting the vendor's name
    straight into a raise site left all of them green.

    So it is asserted here instead, against the classes rather than against a
    call site, where a new error carrying "our Anthropic call failed" is caught
    on the commit that adds it rather than never.
    """
    vendors = (
        "elevenlabs", "eleven labs", "scribe", "gemini", "google", "anthropic",
        "claude", "supabase", "revenuecat", "deepgram", "openai", "postgres",
        "stripe", "s3", "minio",
    )

    def descendants(cls):
        for child in cls.__subclasses__():
            yield child
            yield from descendants(child)

    offenders = [
        f"{error.__name__}: {error.message}"
        for error in descendants(FlintroomError)
        if isinstance(getattr(error, "message", None), str)
        and any(vendor in error.message.lower() for vendor in vendors)
    ]

    assert offenders == []
