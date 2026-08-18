"""Panel endpoints.

Thin, per `CLAUDE.md`: parse the request, call a service, return a response.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.auth.rate_limit import DIFFICULTY_LIMIT
from app.modules.auth.dependencies import rate_limit_user
from app.modules.panels.schemas import ArchetypeCatalogue, DifficultyChoice
from app.modules.panels.service import PanelCatalogueService

router = APIRouter(tags=["panels"])


async def get_catalogue_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PanelCatalogueService:
    return PanelCatalogueService(db)


CatalogueServiceDep = Annotated[PanelCatalogueService, Depends(get_catalogue_service)]


@router.get("/archetypes", response_model=ArchetypeCatalogue)
async def read_archetypes(
    user_id: CurrentUser, catalogue: CatalogueServiceDep
) -> ArchetypeCatalogue:
    """Who may be seated, and how many of them this caller's plan allows.

    Authenticated even though the roster is the same for everybody, because the
    seat count is not: an unauthenticated version would have to answer with the
    free tier's number and would be wrong for every paying caller. Splitting it
    into a public roster and a private cap would be two round trips for one
    screen.
    """
    return await catalogue.catalogue(user_id=user_id)


@router.put(
    "/me/difficulty",
    response_model=DifficultyChoice,
    dependencies=[Depends(rate_limit_user("difficulty", DIFFICULTY_LIMIT))],
)
async def choose_difficulty(
    payload: DifficultyChoice, user_id: CurrentUser, catalogue: CatalogueServiceDep
) -> DifficultyChoice:
    """Set how hard the room will push.

    On `/me` rather than under the catalogue, because the rung is a fact about
    the account and not about the roster — the read rides the catalogue only
    because that is the request the setup screen already makes, and a write has
    no such screen to share.

    Returns what was stored rather than 204. The client has just moved a
    control and needs to render its new position from the server's answer,
    which is also how it learns that a rung it asked for was not the rung it
    got — though today it always is, because an invalid one is refused rather
    than clamped.

    May go down as well as up (`docs/difficulty-calibration.md` decision 5).
    That is safe because level 1 still presses an unanswered question, so this
    control cannot turn the wedge off, and because calibration carries on from
    wherever it is left — it is a starting point, never a floor.
    """
    return DifficultyChoice(
        difficulty=await catalogue.choose(
            user_id=user_id, difficulty=payload.difficulty
        )
    )
