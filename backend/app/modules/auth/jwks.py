"""A provider's published signing keys, fetched and cached.

Satisfies the `SigningKeys` protocol that `OidcVerifier` depends on. Nothing
here decides whether a token is genuine; it only answers "what key does this
provider sign with under this `kid`".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

from app.core.errors import ProviderUnavailable

#: How long to wait before asking a provider for its keys again after a token
#: named one we do not hold.
#:
#: The two failure modes pull in opposite directions. Refetch eagerly and an
#: unrecognised `kid` — which any caller can put in a token — becomes a way to
#: make us hammer Google until they rate-limit us, locking out every real user.
#: Refetch lazily and a genuine key rotation locks everyone out until the
#: window passes.
#:
#: Five minutes settles it because rotation is scheduled and gradual: providers
#: publish a new key alongside the old one well before signing with it, so the
#: worst case is a short window of failed sign-ins, not an outage.
REFRESH_COOLDOWN = timedelta(minutes=5)


class JwksKeys:
    """The JWKS document for one provider."""

    def __init__(
        self,
        *,
        url: str,
        http: httpx.AsyncClient,
        cooldown: timedelta = REFRESH_COOLDOWN,
    ) -> None:
        self._url = url
        self._http = http
        self._cooldown = cooldown
        self._keys: dict[str, Any] = {}
        self._fetched_at: datetime | None = None
        self._last_fetch_failed = False

    async def signing_key(self, *, kid: str) -> Any:
        """The public key published under `kid`, or `LookupError`.

        `LookupError` rather than something louder because an unknown `kid` is
        an ordinary event — it is what a forged token looks like, and also what
        a rotation looks like. `OidcVerifier` turns it into a refused sign-in.
        """
        if kid not in self._keys and self._may_refetch():
            await self._fetch()

        if kid in self._keys:
            return self._keys[kid]

        # Inside the cooldown that follows a failed fetch, a key we do not hold
        # is not evidence of a bad token — it is evidence that we have not been
        # able to ask. Reporting it as a refused sign-in would tell users their
        # credentials are wrong for the duration of somebody else's outage.
        if self._last_fetch_failed:
            raise ProviderUnavailable(
                provider_url=self._url, failed_because="within_cooldown_after_failure"
            )

        raise LookupError(kid)

    def _may_refetch(self) -> bool:
        if self._fetched_at is None:
            return True
        return datetime.now(UTC) - self._fetched_at >= self._cooldown

    async def _fetch(self) -> None:
        # Stamped before the attempt rather than after it. The cooldown governs
        # how often we are willing to *ask*, and a provider that is failing is
        # the one that can least afford being asked again on every request that
        # misses the cache.
        self._fetched_at = datetime.now(UTC)

        try:
            response = await self._http.get(self._url)
            response.raise_for_status()
            document = response.json()
            # Keyed by `kid`, so a key without one is a key nothing can ever
            # look up. Skipped rather than stored under `None`, which would put
            # a null in a `dict[str, ...]` and make every lookup miss it anyway
            # — the same outcome, reached by a shape that lies about itself.
            keys = {
                key.key_id: key.key
                for key in jwt.PyJWKSet.from_dict(document).keys
                if key.key_id is not None
            }
        except (httpx.HTTPError, jwt.PyJWTError, ValueError) as exc:
            # Not a refused sign-in. The caller did nothing wrong and retrying
            # their credential will not help, so this has to stay distinguishable
            # from a bad token — both for the user and for whoever is looking at
            # why the 401 rate moved. The vendor is named in the log context and
            # never in the response.
            self._last_fetch_failed = True
            raise ProviderUnavailable(
                provider_url=self._url, failed_because=type(exc).__name__
            ) from exc

        self._last_fetch_failed = False
        self._keys = keys
