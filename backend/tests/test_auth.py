"""Authentication — who is calling, and can they prove it.

`docs/onboarding.md` settled the sign-in methods (Apple + Google) and left the
provider open; the resolved answer is that we verify their ID tokens ourselves
and mint our own short-lived access token. These tests cover our own token —
the provider verification arrives in its own slice.

The client here deliberately does not run the application lifespan. Lifespan
starts the sweep loop and opens a connection pool, neither of which has anything
to do with whether a bearer token identifies its bearer, and both of which would
make this file depend on a running database.
"""

import uuid
from datetime import timedelta

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.modules.auth.dependencies import get_access_tokens, get_onboarding_service
from app.modules.auth.tokens import AccessTokens

#: Not a secret, and not read from the environment. A test that depends on
#: process environment fails differently on every machine it runs on.
SECRET = "test-signing-key-with-no-production-counterpart"


@pytest.fixture
def tokens() -> AccessTokens:
    return AccessTokens(secret=SECRET)


class NeverAsked:
    """An onboarding service for tests that have no database.

    `/v1/me` grew a second question on 2026-08-20 — whether this account has
    ever described a room, so the launch gate knows whether to ask — and that
    question reads a table. The tests in this file are about *tokens*: they
    build an app with no database on purpose, because a credential either names
    its bearer or does not, and a schema has nothing to do with it.

    So the second question is stubbed rather than answered. Overriding it keeps
    these tests measuring the thing they were written for instead of quietly
    becoming integration tests.
    """

    async def described_a_room(self, *, user_id) -> bool:
        return False


@pytest_asyncio.fixture
async def client(tokens):
    app = create_app()
    app.dependency_overrides[get_access_tokens] = lambda: tokens
    app.dependency_overrides[get_onboarding_service] = NeverAsked
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def test_a_valid_token_identifies_its_bearer(client, tokens):
    """The tracer: a token we issued names the user it was issued for.

    `/v1/me` exists for the app to ask on launch whether the credential it kept
    is still good, so it is both the smallest thing that proves the path and a
    thing the product needs.
    """
    user_id = uuid.uuid4()

    response = await client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {tokens.issue(user_id=user_id)}"},
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == str(user_id)


async def test_a_request_with_no_token_is_refused(client):
    """401, not 403.

    Worth pinning rather than assuming: FastAPI's `HTTPBearer` answers a missing
    header with 403 by default, which tells a client its credential was rejected
    when in fact it never sent one — and sends the app into a sign-in loop it
    cannot escape, because re-authenticating is not the fix for a header it is
    not attaching.
    """
    response = await client.get("/v1/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


async def test_a_token_signed_with_another_key_is_refused(client):
    """A well-formed token is not an authentic one.

    Every field is correct and the structure is valid; only the signature was
    produced by a key that is not ours. If this passes, the signing key is
    decoration and anyone can mint a token for any user_id.
    """
    impostor = AccessTokens(secret="a-key-that-is-not-ours-but-is-long-enough")

    response = await client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {impostor.issue(user_id=uuid.uuid4())}"},
    )

    assert response.status_code == 401


async def test_an_unsigned_token_is_refused(client):
    """The `alg: none` attack, which is the reason `algorithms` is pinned.

    A JWT names its own algorithm in its header, so a verifier that trusts that
    header will happily accept a token whose author declared it needs no
    signature. That is not a hypothetical — it is the best-known flaw in the
    format, and it turns the header into an authentication bypass for any
    user_id an attacker cares to type.

    Pinning the algorithm list on decode is what closes it, and this test is
    what stops someone widening that list to accept a provider token directly.
    """
    unsigned = jwt.encode({"sub": str(uuid.uuid4())}, key="", algorithm="none")

    response = await client.get(
        "/v1/me", headers={"Authorization": f"Bearer {unsigned}"}
    )

    assert response.status_code == 401


async def test_an_expired_token_is_refused(client, tokens):
    """Expiry is the only thing that ends an access token, so it has to hold.

    Nothing is looked up when one is verified, which is what makes the endpoint
    fast and what makes revocation impossible. The fifteen-minute window is the
    entire bound on a stolen credential; a verifier that ignores `exp` removes
    it and turns every token ever issued into a permanent one.
    """
    expired = AccessTokens(secret=SECRET, ttl=timedelta(minutes=-1))

    response = await client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {expired.issue(user_id=uuid.uuid4())}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
