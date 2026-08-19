"""Who is calling, resolved before any handler runs.

`CLAUDE.md` requires authentication as a dependency rather than a check inside a
service, so that an endpoint cannot be written that forgets it.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.errors import NotAuthenticated
from app.core.request_context import current_request_id
from app.modules.auth.rate_limit import RATE_LIMIT_WINDOW, PostgresRateLimiter
from app.modules.billing.deletion import AccountDeletion
from app.modules.auth.refresh import RefreshTokenService
from app.modules.auth.service import AuthService, IdentityVerifier
from app.modules.onboarding.service import OnboardingService
from app.modules.auth.tokens import AccessTokens

#: `auto_error` off so that a missing header reaches our own handler. FastAPI's
#: default raises a bare 403 for an absent credential, which is both the wrong
#: code — nothing has been denied, nothing was presented — and a response shaped
#: unlike every other error the API returns.
bearer_scheme = HTTPBearer(auto_error=False)


def get_access_tokens(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AccessTokens:
    return AccessTokens(secret=settings.jwt_secret)


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    tokens: Annotated[AccessTokens, Depends(get_access_tokens)],
) -> uuid.UUID:
    if credentials is None:
        raise NotAuthenticated()
    return tokens.verify(credentials.credentials)


#: Every authenticated endpoint annotates with this rather than repeating the
#: dependency, so there is one spelling of "this route requires a user".
CurrentUser = Annotated[uuid.UUID, Depends(get_current_user)]


def get_caller_context(user_id: CurrentUser) -> ActorContext:
    """The provenance every service built for this request writes under.

    One place decides what a request's actor looks like. Three modules building
    it themselves is three chances for one of them to drop the request id, and
    a row missing it is indistinguishable from one written by the sweep loop.
    """
    return ActorContext.user(user_id, request_id=current_request_id())


#: Services take this rather than a user id, so a service cannot be constructed
#: for a request without provenance attached.
CallerContext = Annotated[ActorContext, Depends(get_caller_context)]


def get_verifiers(request: Request) -> Mapping[str, IdentityVerifier]:
    """The process-wide verifiers, built at startup.

    Read from application state rather than constructed here: each verifier owns
    a JWKS cache, and one built per request would hold a cache it never gets to
    use.
    """
    return request.app.state.verifiers


async def get_auth_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    verifiers: Annotated[Mapping[str, IdentityVerifier], Depends(get_verifiers)],
) -> AuthService:
    return AuthService(db, verifiers)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
AccessTokensDep = Annotated[AccessTokens, Depends(get_access_tokens)]


async def get_refresh_tokens(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RefreshTokenService:
    return RefreshTokenService(db)


RefreshTokensDep = Annotated[RefreshTokenService, Depends(get_refresh_tokens)]


async def get_account_deletion(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccountDeletion:
    """Deletion as a request reaches it.

    No object store. `request` never touches a bucket — it marks a column and
    revokes tokens — and the purge that does is the sweep's, seven days later.
    Handing an endpoint the store would advertise a capability this path does
    not have and cannot be given: a synchronous purge is not what the architect
    chose.
    """
    return AccountDeletion(db)


AccountDeletionDep = Annotated[AccountDeletion, Depends(get_account_deletion)]


def rate_limit(namespace: str, limit: int) -> Callable[..., Awaitable[None]]:
    """A route dependency that counts this caller's attempt and may refuse it.

    Applied as a dependency rather than called inside a handler so that the
    count happens before any work, and so an endpoint cannot be written that
    forgets it — the same reasoning `CLAUDE.md` gives for authentication.
    """

    async def limited(
        request: Request,
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> None:
        await PostgresRateLimiter(db).check(
            key=f"{namespace}:ip:{_caller(request)}",
            limit=limit,
            window=RATE_LIMIT_WINDOW,
        )

    return limited


def rate_limit_user(namespace: str, limit: int) -> Callable[..., Awaitable[None]]:
    """The same, keyed on the authenticated caller instead of the socket.

    The better key wherever it is available, and it is available on every
    endpoint behind `CurrentUser`. An address is a poor identity in both
    directions: mobile users share carrier NAT in large groups, so one bucket
    covers a whole town, while anyone with a reason to work around the limit
    can generate fresh addresses more easily than fresh accounts.
    """

    async def limited(
        user_id: CurrentUser,
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> None:
        await PostgresRateLimiter(db).check(
            key=f"{namespace}:user:{user_id}",
            limit=limit,
            window=RATE_LIMIT_WINDOW,
        )

    return limited


def _caller(request: Request) -> str:
    """Who to charge this attempt to.

    The socket's peer, never a forwarded header. `X-Forwarded-For` is written by
    whoever is calling, so trusting it hands every attacker an unlimited supply
    of identities and makes the limiter decorative.

    The consequence is a deployment requirement: behind a load balancer this is
    the balancer, and every user shares one bucket. The proxy has to be told to
    rewrite the peer — uvicorn's `--proxy-headers` with `--forwarded-allow-ips`
    set to the balancer, so the header is trusted from exactly one source and
    nobody else.
    """
    return request.client.host if request.client else "unknown"


async def get_onboarding_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OnboardingService:
    """What somebody said about the room they are preparing for.

    Here rather than in an `onboarding/dependencies.py` of its own, because both
    callers live on this router: sign-in has always written the answers, and
    `/v1/me` now reads whether they exist. A module with one dependency and no
    router is a file nobody would find.
    """
    return OnboardingService(db)


OnboardingServiceDep = Annotated[OnboardingService, Depends(get_onboarding_service)]
