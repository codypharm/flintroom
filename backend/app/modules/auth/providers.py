"""The identity providers we accept, as configuration.

Apple and Google differ only in three constants, which is the whole argument for
`OidcVerifier` being one class. Adding an enterprise OIDC provider for the Teams
tier — the forward constraint recorded in `docs/onboarding.md` — is an entry in
this file rather than an integration.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.modules.auth.jwks import JwksKeys
from app.modules.auth.oidc import OidcVerifier


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    #: Google publishes tokens under both spellings and has done for years, so
    #: accepting one is a sign-in that fails for a subset of users.
    issuers: tuple[str, ...]
    jwks_url: str


GOOGLE = ProviderConfig(
    name="google",
    issuers=("https://accounts.google.com", "accounts.google.com"),
    jwks_url="https://www.googleapis.com/oauth2/v3/certs",
)

APPLE = ProviderConfig(
    name="apple",
    issuers=("https://appleid.apple.com",),
    jwks_url="https://appleid.apple.com/auth/keys",
)


def build_verifiers(
    settings: Settings, http: httpx.AsyncClient
) -> dict[str, OidcVerifier]:
    """One verifier per provider, built once for the life of the process.

    Built at startup rather than per request because each one owns a key cache.
    Per-request construction would discard that cache every time and fetch the
    JWKS on every single sign-in — which is both the latency the cache exists to
    avoid and the provider hammering `REFRESH_COOLDOWN` exists to prevent.
    """
    audiences = {GOOGLE.name: settings.google_client_id, APPLE.name: settings.apple_client_id}

    return {
        config.name: OidcVerifier(
            provider=config.name,
            issuers=config.issuers,
            audience=audiences[config.name],
            keys=JwksKeys(url=config.jwks_url, http=http),
        )
        for config in (GOOGLE, APPLE)
    }
