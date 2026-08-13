"""Who is calling, resolved before any handler runs.

`CLAUDE.md` requires authentication as a dependency rather than a check inside a
service, so that an endpoint cannot be written that forgets it.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.errors import NotAuthenticated
from app.modules.auth.refresh import RefreshTokenService
from app.modules.auth.service import AuthService, IdentityVerifier
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
