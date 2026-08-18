"""Authentication endpoints.

Thin, per `CLAUDE.md`: parse the request, call a service, return a response. No
business logic and no database access at this layer.
"""

from fastapi import APIRouter, Depends, Response, status

from app.modules.auth.dependencies import (
    AccessTokensDep,
    AccountDeletionDep,
    AuthServiceDep,
    CurrentUser,
    RefreshTokensDep,
    rate_limit,
    rate_limit_user,
)
from app.modules.auth.schemas import (
    DeletionScheduled,
    Identity,
    RefreshRequest,
    SignInRequest,
    SignedIn,
)
from app.modules.auth.rate_limit import (
    ACCOUNT_DELETION_LIMIT,
    REFRESH_LIMIT,
    SIGN_IN_LIMIT,
)
from app.modules.auth.tokens import ACCESS_TOKEN_TTL

router = APIRouter(tags=["auth"])


@router.get("/me", response_model=Identity)
async def read_current_identity(user_id: CurrentUser) -> Identity:
    """Answer whether the credential the app is holding is still good.

    The mobile client calls this on launch. A 200 means go straight in; a 401
    means sign in again.
    """
    return Identity(user_id=user_id)


@router.delete(
    "/me",
    response_model=DeletionScheduled,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(rate_limit_user("account_deletion", ACCOUNT_DELETION_LIMIT))
    ],
)
async def delete_current_account(
    user_id: CurrentUser, deletion: AccountDeletionDep
) -> DeletionScheduled:
    """Ask for this account to be destroyed.

    Apple has required this since 2022 for any app supporting account creation,
    so it is a store blocker rather than a courtesy — and `docs/privacy-policy.md`
    cannot be published while it claims a control that does not exist.

    `DELETE /me` rather than a POST to a sub-resource, because the account is
    the thing being deleted and it is the resource this token already
    identifies. Nothing is read from the request: no body, no path parameter,
    nothing a caller could point at somebody else's account.

    **202, not 204.** The window means nothing has been destroyed yet, and a
    204 would say otherwise on the one endpoint where overstating what happened
    is worst. The body carries the date so the app can say how long the user
    has to change their mind.

    Repeating it is not an error. A retry returns the same date rather than a
    409 — the app would otherwise have to render "already scheduled" as a
    failure, on the screen where a confusing answer costs the most trust.
    """
    return DeletionScheduled(purge_at=await deletion.request(user_id=user_id))


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
    admitted = await auth.sign_in(
        provider=payload.provider, id_token=payload.id_token
    )

    return SignedIn(
        access_token=tokens.issue(user_id=admitted.user_id),
        refresh_token=await refresh.issue(user_id=admitted.user_id),
        expires_in=int(ACCESS_TOKEN_TTL.total_seconds()),
        deletion_cancelled=admitted.deletion_cancelled,
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


@router.post(
    "/auth/sessions/sign-out",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("sign_out", REFRESH_LIMIT))],
)
async def sign_out(payload: RefreshRequest, refresh: RefreshTokensDep) -> Response:
    """End this session.

    Takes the refresh token rather than a bearer credential, because sign-out
    has to work once the access token has expired — which is the state a
    returning user is in before anything else happens.

    Always 204. Whether the token was real is not something this endpoint will
    tell an unauthenticated caller.
    """
    await refresh.sign_out(token=payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
