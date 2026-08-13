"""Fetching the public keys a provider signs with.

The other half of `OidcVerifier`, deliberately separated: verification is a pure
decision about a string, this is I/O with a cache and a rotation policy. Keeping
them apart is what let the verification be proven without a network, and it is
what lets this be tested without a real one.

The transport is stubbed; everything above it — the HTTP call, the JWKS parsing,
the caching — is the real implementation.
"""

from __future__ import annotations

import json

from datetime import timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from freezegun import freeze_time

from app.core.errors import ProviderUnavailable
from app.modules.auth.jwks import JwksKeys

JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
KEY_ID = "published-key-1"


@pytest.fixture(scope="session")
def provider_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def as_jwks(*keys: tuple[str, rsa.RSAPrivateKey]) -> dict:
    """The document a provider actually publishes."""
    return {
        "keys": [
            {
                **json.loads(
                    jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key())
                ),
                "kid": kid,
                "alg": "RS256",
                "use": "sig",
            }
            for kid, private in keys
        ]
    }


class FakeProvider:
    """Google's JWKS endpoint, counting how often it is asked."""

    def __init__(self, document: dict) -> None:
        self.document = document
        self.calls = 0
        self.status = 200

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.calls += 1
            if self.status != 200:
                return httpx.Response(self.status)
            return httpx.Response(200, json=self.document)

        return httpx.MockTransport(handle)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport())


async def test_it_returns_the_key_the_provider_published(provider_key):
    """The tracer.

    Asserted by using the key rather than by comparing it to another object: a
    signing key is only correct if it verifies what the matching private key
    signed, and that is the only property anything downstream cares about.
    """
    provider = FakeProvider(as_jwks((KEY_ID, provider_key)))
    signed = jwt.encode(
        {"sub": "someone"}, provider_key, algorithm="RS256", headers={"kid": KEY_ID}
    )

    async with provider.client() as http:
        keys = JwksKeys(url=JWKS_URL, http=http)
        key = await keys.signing_key(kid=KEY_ID)

    assert jwt.decode(signed, key, algorithms=["RS256"])["sub"] == "someone"


async def test_a_key_already_held_is_not_fetched_again(provider_key):
    """Sign-in must not put an HTTPS round trip in front of every request.

    Providers rotate keys on the order of days, so re-reading the document per
    token is latency and a dependency on Google being reachable, bought for
    nothing.
    """
    provider = FakeProvider(as_jwks((KEY_ID, provider_key)))

    async with provider.client() as http:
        keys = JwksKeys(url=JWKS_URL, http=http)
        await keys.signing_key(kid=KEY_ID)
        await keys.signing_key(kid=KEY_ID)

    assert provider.calls == 1


async def test_a_provider_outage_is_not_reported_as_a_bad_token(provider_key):
    """"Google is down" and "your sign-in is invalid" are different answers.

    Collapsing them sends a user who did nothing wrong into a sign-in loop that
    cannot succeed, and hides a provider incident inside our 401 rate where no
    alert will ever find it.

    The vendor is not named in what reaches the client, per `CLAUDE.md` — it
    exposes internal architecture and goes stale the moment a provider changes.
    And the second attempt makes no second call: a provider that is failing is
    the one that can least afford being retried on every request.
    """
    provider = FakeProvider(as_jwks((KEY_ID, provider_key)))
    provider.status = 503

    async with provider.client() as http:
        keys = JwksKeys(url=JWKS_URL, http=http)
        with pytest.raises(ProviderUnavailable) as failure:
            await keys.signing_key(kid=KEY_ID)
        with pytest.raises(ProviderUnavailable):
            await keys.signing_key(kid=KEY_ID)

    assert "google" not in failure.value.message.lower()
    assert provider.calls == 1


async def test_keys_already_held_survive_a_provider_outage(provider_key):
    """An identity provider's bad afternoon should not be ours.

    Users already signed in are unaffected — nothing is fetched to verify our
    own tokens — and a user signing in with a key we already hold gets through
    too. The cache is what makes the blast radius "new keys only" rather than
    "everyone".
    """
    provider = FakeProvider(as_jwks((KEY_ID, provider_key)))
    signed = jwt.encode(
        {"sub": "someone"}, provider_key, algorithm="RS256", headers={"kid": KEY_ID}
    )

    async with provider.client() as http:
        keys = JwksKeys(url=JWKS_URL, http=http)
        await keys.signing_key(kid=KEY_ID)

        provider.status = 503
        key = await keys.signing_key(kid=KEY_ID)

    assert jwt.decode(signed, key, algorithms=["RS256"])["sub"] == "someone"


async def test_a_rotated_key_is_picked_up_once_the_cooldown_passes(provider_key):
    """The cooldown bounds the damage; it must not become the damage.

    Providers rotate on their own schedule and do not tell us. A cache that
    refuses to look again is an outage on rotation day — every sign-in failing,
    for a reason entirely outside our logs, with nothing wrong on our side.

    Both halves are asserted here: the new key is refused while the window is
    open, and found once it has passed. Testing only the second half would pass
    against an implementation with no cooldown at all.
    """
    rotated_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    provider = FakeProvider(as_jwks((KEY_ID, provider_key)))

    with freeze_time("2026-08-13 09:00:00") as clock:
        async with provider.client() as http:
            keys = JwksKeys(url=JWKS_URL, http=http)
            await keys.signing_key(kid=KEY_ID)

            provider.document = as_jwks(
                (KEY_ID, provider_key), ("rotated-key", rotated_key)
            )
            with pytest.raises(LookupError):
                await keys.signing_key(kid="rotated-key")

            clock.tick(timedelta(minutes=6))
            key = await keys.signing_key(kid="rotated-key")

    signed = jwt.encode(
        {"sub": "after-rotation"},
        rotated_key,
        algorithm="RS256",
        headers={"kid": "rotated-key"},
    )
    assert jwt.decode(signed, key, algorithms=["RS256"])["sub"] == "after-rotation"
    assert provider.calls == 2


async def test_an_unknown_key_does_not_refetch_on_every_attempt(provider_key):
    """A cache miss is attacker-controlled, and that makes it dangerous.

    The `kid` comes out of a token supplied by whoever is calling. If an
    unrecognised one triggers a fetch, anyone can make us call Google as fast
    as they can send requests — turning our sign-in endpoint into a way to get
    our own IP rate-limited by our identity provider, which locks out every
    real user. The attacker needs no account and no valid token to do it.

    So the refetch is bounded by time, not by attempts.
    """
    provider = FakeProvider(as_jwks((KEY_ID, provider_key)))

    async with provider.client() as http:
        keys = JwksKeys(url=JWKS_URL, http=http)
        for _ in range(5):
            with pytest.raises(LookupError):
                await keys.signing_key(kid="never-published")

    assert provider.calls == 1
