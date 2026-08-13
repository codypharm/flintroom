"""Authentication endpoints.

Thin, per `CLAUDE.md`: parse the request, call a service, return a response. No
business logic and no database access at this layer.
"""

from fastapi import APIRouter

from app.modules.auth.dependencies import CurrentUser
from app.modules.auth.schemas import Identity

router = APIRouter(tags=["auth"])


@router.get("/me", response_model=Identity)
async def read_current_identity(user_id: CurrentUser) -> Identity:
    """Answer whether the credential the app is holding is still good.

    The mobile client calls this on launch. A 200 means go straight in; a 401
    means sign in again.
    """
    return Identity(user_id=user_id)
