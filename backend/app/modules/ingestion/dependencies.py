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


async def get_tier_limits(
    caller: CallerContext,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IngestionService:
    """Ingestion, for the one call that stops at the database — #72.

    `limits` reads the tier table and nothing else: no signed URL, no listing,
    no `self._storage` anywhere in it. Resolved through `IngestionServiceDep` it
    was nonetheless unreachable in any deployment without a bucket, because that
    dependency resolves object storage in order to *construct* a service — so an
    endpoint whose entire purpose is to be readable before anybody uploads
    anything answered 502 whenever there was nowhere to upload to.

    That is not only a dev-box problem. The tier table has one home precisely so
    the app does not ship its own copy, and the app refuses an oversized file
    locally before it reads a byte. Both of those are lost exactly when storage
    is degraded, which is the moment the app most needs to say what is going on
    — and this is the one ingestion call that can still answer honestly then.

    **The wall is not moved, only the wiring.** `IngestionService._storage`
    raises the same typed, vendor-anonymous refusal the moment anything asks it
    to sign or store, so a registration made against this service still fails
    with a 502 rather than handing out a URL to nowhere.

    A whole dependency rather than a default argument, so this is opt-in per
    endpoint and readable in the signature. Nothing acquires a storage-free
    service by forgetting to ask for one.
    """
    return IngestionService(db, actor=caller)


TierLimitsDep = Annotated[IngestionService, Depends(get_tier_limits)]


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
