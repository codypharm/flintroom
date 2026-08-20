"""Panel endpoints.

Thin, per `CLAUDE.md`: parse the request, call a service, return a response.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.auth.rate_limit import AUTHORING_LIMIT, DIFFICULTY_LIMIT
from app.modules.auth.dependencies import rate_limit_user
from app.modules.panels.authoring import AuthoringService
from app.modules.panels.schemas import (
    ArchetypeCatalogue,
    ArchetypeDraft,
    AuthoredArchetypeRead,
    DifficultyChoice,
)
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


async def get_authoring_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthoringService:
    return AuthoringService(db)


AuthoringDep = Annotated[AuthoringService, Depends(get_authoring_service)]

#: One budget across every write here — see `AUTHORING_LIMIT`.
_authoring_budget = Depends(rate_limit_user("archetype_authoring", AUTHORING_LIMIT))


@router.get("/archetypes/mine", response_model=list[AuthoredArchetypeRead])
async def read_my_archetypes(
    user_id: CurrentUser, authoring: AuthoringDep
) -> list[AuthoredArchetypeRead]:
    """The panelists this account wrote, live ones only.

    Empty rather than 404 for an account that has written none: nothing is
    missing, they simply have no panel yet, and a client that had to branch on
    404 to render an empty list would treat "no panelists" as an error state.

    Their own `persona` comes back, unlike a shipped archetype's, whose prompt
    text never leaves the server. There is nothing to protect — they wrote it,
    and the form has to be able to reopen it. What stays ours is the attack
    strategy composed around it, which is absent from the schema entirely.

    Not rate-limited. It is a read, and the setup screen makes it on open.
    """
    return [
        AuthoredArchetypeRead.model_validate(row)
        for row in await authoring.roster(user_id=user_id)
    ]


@router.post(
    "/archetypes/mine",
    response_model=AuthoredArchetypeRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_authoring_budget],
)
async def write_archetype(
    draft: ArchetypeDraft, user_id: CurrentUser, authoring: AuthoringDep
) -> AuthoredArchetypeRead:
    """Write a panelist.

    201 with the row, because the client needs the minted name: it is what
    `SessionStart.archetypes` takes, and without it the form would have to
    re-read the roster to find what it just created.
    """
    return AuthoredArchetypeRead.model_validate(
        await authoring.write(user_id=user_id, draft=draft)
    )


@router.put(
    "/archetypes/mine/{name}",
    response_model=AuthoredArchetypeRead,
    dependencies=[_authoring_budget],
)
async def revise_archetype(
    name: str,
    draft: ArchetypeDraft,
    user_id: CurrentUser,
    authoring: AuthoringDep,
) -> AuthoredArchetypeRead:
    """Edit a panelist, whole.

    PUT rather than PATCH: the form holds every field and sends every field, so
    a partial update would be a shape the client never produces and a second
    merge rule to get wrong.

    **The returned `name` may not be the one in the path.** A panelist that has
    been seated is replaced rather than mutated, so old rooms keep pointing at
    the text that was actually in them (`docs/custom-archetypes.md` §4) — which
    is exactly why the row comes back rather than a 204. A client that assumed
    the name survived would hold a stale one.
    """
    return AuthoredArchetypeRead.model_validate(
        await authoring.revise(user_id=user_id, name=name, draft=draft)
    )


@router.delete(
    "/archetypes/mine/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_authoring_budget],
)
async def retire_archetype(
    name: str, user_id: CurrentUser, authoring: AuthoringDep
) -> Response:
    """Take a panelist out of the panel.

    **DELETE, and it archives.** The verb is the client's, the behaviour is
    ours: the row stays so every past room can still say who was in it, and
    §4 requires the *control* to read "remove from your panel" rather than
    "delete" for the same reason. `docs/privacy-policy.md` has to say what
    actually happens — account deletion is the real delete.

    Idempotent, so a retried request whose response was lost still answers 204
    rather than telling somebody their panelist has vanished.
    """
    await authoring.retire(user_id=user_id, name=name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
