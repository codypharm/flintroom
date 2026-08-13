"""Who is calling, resolved before any handler runs.

`CLAUDE.md` requires authentication as a dependency rather than a check inside a
service, so that an endpoint cannot be written that forgets it.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.errors import NotAuthenticated
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
