"""Verifying an Apple or Google ID token.

This is the decision from `docs/onboarding.md` made concrete: no managed auth
provider, so the check that a sign-in is genuine happens here. Everything
downstream — the account, the ledger, the minutes — trusts whatever this
function returns, which makes it the single place in the product where being
approximately right is the same as being wrong.

The tokens below are signed with a real RSA key and verified with real RS256.
Only the key *distribution* is stubbed. A test that mocks the verification
itself would prove nothing about the verification.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.errors import NotAuthenticated
from app.modules.auth.oidc import OidcVerifier

GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_AUDIENCE = "flintroom.apps.googleusercontent.com"
KEY_ID = "test-signing-key"


@pytest.fixture(scope="session")
def provider_key() -> rsa.RSAPrivateKey:
    """Stands in for the private key Google signs with and never shares."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StubKeys:
    """The JWKS endpoint, without the network.

    Production fetches and caches Google's published keys over HTTPS. What that
    machinery must deliver is exactly this: a public key for a `kid`.
    """

    def __init__(self, key: rsa.RSAPrivateKey) -> None:
        self._key = key

    async def signing_key(self, *, kid: str):
        if kid != KEY_ID:
            raise LookupError(kid)
        return self._key.public_key()


@pytest.fixture
def verifier(provider_key) -> OidcVerifier:
    return OidcVerifier(
        provider="google",
        issuers=(GOOGLE_ISSUER,),
        audience=GOOGLE_AUDIENCE,
        keys=StubKeys(provider_key),
    )


def id_token(
    provider_key: rsa.RSAPrivateKey,
    *,
    subject: str = "google-subject-1",
    email: str = "someone@example.com",
    email_verified: bool = True,
    audience: str = GOOGLE_AUDIENCE,
    issuer: str = GOOGLE_ISSUER,
    expires_in: timedelta = timedelta(hours=1),
    key_id: str = KEY_ID,
) -> str:
    """A token shaped the way Google actually issues them."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": subject,
            "email": email,
            "email_verified": email_verified,
            "iat": now,
            "exp": now + expires_in,
        },
        provider_key,
        algorithm="RS256",
        headers={"kid": key_id},
    )


async def test_a_genuine_token_yields_the_identity_it_asserts(verifier, provider_key):
    """The tracer: a token signed by the provider names its bearer.

    `subject` is the part that matters and the part that is easy to get wrong.
    It is the provider's stable identifier for this person, unique only within
    that provider — which is why it is never used alone as an identity, and why
    the provider travels with it everywhere it goes.
    """
    identity = await verifier.verify(
        id_token(provider_key, subject="google-subject-1", email="dana@example.com")
    )

    assert identity.provider == "google"
    assert identity.subject == "google-subject-1"
    assert identity.email == "dana@example.com"
    assert identity.email_verified is True


async def test_a_token_minted_for_another_app_is_refused(verifier, provider_key):
    """The one that matters most, and the one most often left out.

    This token is entirely genuine. Google really did sign it, the signature
    verifies, it has not expired, and the person it describes is real. It was
    simply issued to a different application.

    Anyone can register a Google app. If the audience is not pinned to our own
    client ID, they collect a legitimate token from any of their users and
    present it here — and we sign them in as that person, with that person's
    minutes and that person's session history. There is no signature check that
    catches this, because nothing is forged.
    """
    with pytest.raises(NotAuthenticated):
        await verifier.verify(
            id_token(provider_key, audience="someone-elses.apps.googleusercontent.com")
        )


async def test_a_token_from_another_issuer_is_refused(verifier, provider_key):
    """`iss` is what stops one provider's subject being read as another's.

    Subjects are unique only within a provider. A token claiming to be from
    Apple, verified against Google's rules, lets an attacker choose a `sub`
    that already belongs to a Google user here.
    """
    with pytest.raises(NotAuthenticated):
        await verifier.verify(
            id_token(provider_key, issuer="https://appleid.apple.com")
        )


async def test_a_token_signed_by_an_unknown_key_is_refused(verifier):
    """Anyone can generate an RSA key. Only the provider's keys count.

    Signed correctly, structured correctly, and by the wrong hands — which is
    what a forged sign-in actually looks like.
    """
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    with pytest.raises(NotAuthenticated):
        await verifier.verify(id_token(attacker_key))


async def test_a_token_naming_an_unpublished_key_is_refused(verifier, provider_key):
    """An unknown `kid` is a refusal, not a lookup failure.

    Providers rotate keys, so an unrecognised `kid` has an innocent explanation
    and will happen in production. It still cannot be allowed to surface as
    anything other than a rejected sign-in.
    """
    with pytest.raises(NotAuthenticated):
        await verifier.verify(id_token(provider_key, key_id="never-published"))


async def test_an_expired_token_is_refused(verifier, provider_key):
    """Provider ID tokens are short-lived, and replay is the reason.

    Without this, a token captured once is a permanent credential.
    """
    with pytest.raises(NotAuthenticated):
        await verifier.verify(id_token(provider_key, expires_in=timedelta(hours=-1)))


async def test_an_unverified_email_is_reported_as_unverified(verifier, provider_key):
    """Carried through honestly, because linking depends on it.

    `docs/onboarding.md` links accounts on a verified email and forbids it on
    an unverified one — that is the classic account-takeover path. This is the
    flag that decision reads, so losing it here would quietly defeat the rule
    two layers up, where nobody would think to look for it.
    """
    identity = await verifier.verify(id_token(provider_key, email_verified=False))

    assert identity.email_verified is False
