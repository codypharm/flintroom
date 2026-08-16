"""What an ingestion endpoint needs before it runs."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ProviderUnavailable
from app.core.logging import get_logger
from app.core.storage import ObjectStorage
from app.modules.auth.dependencies import CallerContext, CurrentUser
from app.modules.ingestion.models import Material
from app.modules.ingestion.service import IngestionService

log = get_logger(__name__, tag="ingestion")


def get_object_storage(request: Request) -> ObjectStorage:
    """The process-wide store, built once in the application lifespan.

    A deployment without a bucket fails here rather than at boot, for the reason
    `build_object_storage` gives: auth, balances and the voice loop all work
    without one, and refusing to start would take them down over a feature none
    of them use.

    Typed and vendor-anonymous. `ProviderUnavailable` must not name what is
    missing (CLAUDE.md) — the client learns that attaching material is
    unavailable, not which storage vendor we buy.
    """
    storage = getattr(request.app.state, "object_storage", None)
    if storage is None:
        log.error("object_storage_unconfigured")
        raise ProviderUnavailable(reason="storage_unconfigured")
    return storage


ObjectStorageDep = Annotated[ObjectStorage, Depends(get_object_storage)]


async def get_ingestion_service(
    caller: CallerContext,
    db: Annotated[AsyncSession, Depends(get_db)],
    storage: ObjectStorageDep,
) -> IngestionService:
    """Ingestion, attributed to the caller who asked for it.

    Provenance is set at construction rather than passed per call, as everywhere
    else: it is what makes *"the user deleted this material at 14:32"* a claim
    the audit trail can support, rather than an event the sweep might equally
    have caused.
    """
    return IngestionService(db, storage=storage, actor=caller)


IngestionServiceDep = Annotated[IngestionService, Depends(get_ingestion_service)]


async def get_owned_material(
    material_id: uuid.UUID, user_id: CurrentUser, ingestion: IngestionServiceDep
) -> Material:
    """Resolve the material named in the path, for the caller who owns it.

    Ownership is inside the query rather than checked after it, so there is no
    route in this module that can reach a material without a user — the same
    reasoning `OwnedSession` follows, and the same reason not-found is the
    answer to both "no such thing" and "not yours".
    """
    return await ingestion.get(material_id, user_id=user_id)


#: Every route naming a material in its path annotates with this rather than
#: taking a raw `material_id`, so no endpoint can be added that forgets the
#: ownership check.
OwnedMaterial = Annotated[Material, Depends(get_owned_material)]
