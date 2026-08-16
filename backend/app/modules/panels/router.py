"""Panel endpoints.

Thin, per `CLAUDE.md`: parse the request, call a service, return a response.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.panels.schemas import ArchetypeCatalogue
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
