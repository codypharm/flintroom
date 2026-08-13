"""Our own access token.

Issued after an Apple or Google ID token has been verified, and short-lived by
design: it is a bearer credential the API trusts without a database lookup, so
the window in which a stolen one is useful has to be small. Anything that needs
to outlive that window is the refresh token's job.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.errors import NotAuthenticated

#: Fifteen minutes. Long enough that refreshes are rare, short enough that it
#: bounds the damage from a leaked token — revocation cannot reach a token the
#: API never looks up, so expiry is the only thing that ends it.
ACCESS_TOKEN_TTL = timedelta(minutes=15)

#: Symmetric, because one service both issues and verifies these. Asymmetric
#: signing buys the ability to verify without holding the signing key, and there
#: is nobody here who needs that.
ALGORITHM = "HS256"


class AccessTokens:
    """Issues and verifies the token the mobile app carries."""

    def __init__(self, *, secret: str, ttl: timedelta = ACCESS_TOKEN_TTL) -> None:
        self._secret = secret
        self._ttl = ttl

    def issue(self, *, user_id: uuid.UUID) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {"sub": str(user_id), "iat": now, "exp": now + self._ttl},
            self._secret,
            algorithm=ALGORITHM,
        )

    def verify(self, token: str) -> uuid.UUID:
        """Return the user the token was issued for, or refuse it.

        Every rejection is the same `NotAuthenticated` with the same message.
        Telling a caller whether their token was expired, forged or malformed
        is telling an attacker which half of the problem to work on, and the
        client's correct response is identical in all three cases: sign in
        again. The distinction is kept in the log, where it is useful and where
        only we can read it.
        """
        try:
            claims = jwt.decode(token, self._secret, algorithms=[ALGORITHM])
            return uuid.UUID(claims["sub"])
        except (jwt.PyJWTError, KeyError, ValueError) as exc:
            # The token itself is never logged — it is a live credential until
            # it expires, and a log is a place things get copied out of.
            raise NotAuthenticated(rejected_because=type(exc).__name__) from exc
