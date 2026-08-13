"""Authentication endpoints.

Thin, per `CLAUDE.md`: parse the request, call a service, return a response. No
business logic and no database access at this layer.
"""

from fastapi import APIRouter, Depends

from app.modules.auth.dependencies import (
    AccessTokensDep,
    AuthServiceDep,
    CurrentUser,
    RefreshTokensDep,
    rate_limit,
)
from app.modules.auth.schemas import Identity, RefreshRequest, SignedIn, SignInRequest
from app.modules.auth.rate_limit import REFRESH_LIMIT, SIGN_IN_LIMIT
from app.modules.auth.tokens import ACCESS_TOKEN_TTL

router = APIRouter(tags=["auth"])


@router.get("/me", response_model=Identity)
async def read_current_identity(user_id: CurrentUser) -> Identity:
    """Answer whether the credential the app is holding is still good.

    The mobile client calls this on launch. A 200 means go straight in; a 401
    means sign in again.
    """
    return Identity(user_id=user_id)


@router.post(
    "/auth/sessions",
    response_model=SignedIn,
    dependencies=[Depends(rate_limit("sign_in", SIGN_IN_LIMIT))],
)
async def sign_in(
    payload: SignInRequest,
    auth: AuthServiceDep,
    tokens: AccessTokensDep,
    refresh: RefreshTokensDep,
) -> SignedIn:
    """Exchange a provider ID token for one of ours.

    A POST that creates a session rather than a user: whether an account is
    created is an implementation detail of who turns out to be signing in, and
    the client cannot know in advance. Repeating the call is safe and returns
    the same user, so a retry on a flaky connection costs nothing.
    """
    user_id = await auth.sign_in(provider=payload.provider, id_token=payload.id_token)

    return SignedIn(
        access_token=tokens.issue(user_id=user_id),
        refresh_token=await refresh.issue(user_id=user_id),
        expires_in=int(ACCESS_TOKEN_TTL.total_seconds()),
    )


@router.post(
    "/auth/sessions/refresh",
    response_model=SignedIn,
    dependencies=[Depends(rate_limit("refresh", REFRESH_LIMIT))],
)
async def refresh_session(
    payload: RefreshRequest, tokens: AccessTokensDep, refresh: RefreshTokensDep
) -> SignedIn:
    """Trade a refresh token for a fresh pair.

    No bearer token required, and deliberately so: the whole point is to be
    reachable once the access token has expired.
    """
    user_id, rotated = await refresh.rotate(token=payload.refresh_token)

    return SignedIn(
        access_token=tokens.issue(user_id=user_id),
        refresh_token=rotated,
        expires_in=int(ACCESS_TOKEN_TTL.total_seconds()),
    )
