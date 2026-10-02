"""Verifying an ID token issued by an OpenID Connect provider.

Apple and Google are both OIDC, so they are two configurations of this class
rather than two integrations. That is also what makes the Teams SSO constraint
in `docs/onboarding.md` a config entry later instead of a second implementation
— the provider sits behind an interface, decided on its own merits, exactly as
`CLAUDE.md` requires of the voice and storage providers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import jwt

from app.core.errors import NotAuthenticated

#: Both Apple and Google sign with RS256. Pinned rather than read from the
#: token header for the same reason our own tokens pin theirs: a JWT that
#: nominates its own algorithm can nominate one that needs no key.
ALGORITHMS = ["RS256"]


@dataclass(frozen=True)
class ProviderIdentity:
    """Who a provider says this is.

    `subject` is unique only within a provider, so the pair is the identity and
    neither half travels alone.
    """

    provider: str
    subject: str
    email: str | None
    email_verified: bool


class SigningKeys(Protocol):
    """Where a provider's public keys come from.

    Separated from verification because key distribution is I/O with caching
    and rotation to think about, while verification is a pure decision about a
    string. Keeping them apart is what lets the decision be tested without a
    network.
    """

    async def signing_key(self, *, kid: str) -> Any: ...


class OidcVerifier:
    """One provider's ID tokens."""

    def __init__(
        self,
        *,
        provider: str,
        issuers: tuple[str, ...],
        audience: tuple[str, ...],
        keys: SigningKeys,
    ) -> None:
        self._provider = provider
        self._issuers = issuers
        self._audience = audience
        self._keys = keys

    async def verify(self, id_token: str) -> ProviderIdentity:
        """Return who the provider vouches for, or refuse the token.

        `audience` is the check people leave out, and it is the one that matters
        most. A Google ID token is a genuine, correctly-signed Google token no
        matter which app it was minted for — so without pinning the audience to
        our own client ID, any developer with a Google app can hand us a valid
        token for one of their users and sign in as them here.
        """
        try:
            header = jwt.get_unverified_header(id_token)
            key = await self._keys.signing_key(kid=header.get("kid", ""))
            claims = jwt.decode(
                id_token,
                key,
                algorithms=ALGORITHMS,
                # A list, not a value: PyJWT accepts a token whose `aud`
                # matches any entry, which is what lets one backend serve
                # the web, iOS and Android clients of one project.
                audience=list(self._audience),
                issuer=list(self._issuers),
                options={"require": ["iss", "aud", "sub", "exp"]},
            )
        except (jwt.PyJWTError, LookupError, ValueError) as exc:
            # As with our own tokens: the reason is logged, never returned.
            raise NotAuthenticated(
                provider=self._provider, rejected_because=type(exc).__name__
            ) from exc

        return ProviderIdentity(
            provider=self._provider,
            subject=claims["sub"],
            email=claims.get("email"),
            #: Absent means unverified. `docs/onboarding.md` forbids linking on
            #: an unverified email, so the default here has to be the safe one.
            email_verified=_vouched(claims.get("email_verified")),
        )


def _vouched(flag: object) -> bool:
    """Whether the provider vouched for the email, read strictly.

    Apple documents `email_verified` as a boolean *or* the string "true" or
    "false"; Google sends a boolean. This was `bool(flag)` until 2026-10-02,
    and every non-empty string is truthy, so Apple's "false" read as verified,
    which is the one value linking must never trust. Only `True` or the word
    "true" counts; anything else, including a value nobody documented, is
    unverified, because a wrong "no" costs a duplicate account and a wrong
    "yes" can hand somebody else's account over.
    """
    if isinstance(flag, bool):
        return flag
    return isinstance(flag, str) and flag.strip().lower() == "true"
