"""Material endpoints.

Thin, per `CLAUDE.md`: parse the request, call a service, return a response.

Three calls make an upload, and the middle one is not here. The client PUTs its
bytes straight to storage with a URL this module signs — material is *"delivered
via presigned URL only, never proxied"*, and a deck is exactly the size of thing
that rule exists to keep out of a worker process.
"""

from fastapi import APIRouter, Depends, status

from app.modules.auth.dependencies import CurrentUser, rate_limit_user
from app.modules.auth.rate_limit import MATERIAL_REGISTER_LIMIT
from app.modules.ingestion.dependencies import IngestionServiceDep, OwnedMaterial
from app.modules.ingestion.schemas import (
    MaterialDeclaration,
    MaterialLimits,
    MaterialRead,
    MaterialUpload,
)

router = APIRouter(tags=["materials"])


#: Declared before `/materials/{material_id}`, and it has to be. FastAPI matches
#: in declaration order, so the parameterised route would swallow `limits` and
#: answer a malformed-UUID 422 — a failure nobody would think to look for in a
#: line ordering.
@router.get("/materials/limits", response_model=MaterialLimits)
async def read_limits(
    user_id: CurrentUser, ingestion: IngestionServiceDep
) -> MaterialLimits:
    """What this caller may upload, and what the rung above would allow.

    Published so the app can refuse an oversized file locally, before it reads a
    byte. The refusal in `register_material` stays the real wall — this exists so
    the tier table has one home rather than a second copy shipped in an app
    release.
    """
    return await ingestion.limits(user_id=user_id)


@router.post(
    "/materials",
    response_model=MaterialUpload,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(rate_limit_user("material_register", MATERIAL_REGISTER_LIMIT))
    ],
)
async def register_material(
    declaration: MaterialDeclaration,
    user_id: CurrentUser,
    ingestion: IngestionServiceDep,
) -> MaterialUpload:
    """Claim somewhere to put a deck, and get the one URL that may fill it.

    The user is taken from the credential, never from the body: a client that
    could name the account would be able to upload into somebody else's storage
    prefix and read it back.

    Refusals happen inside the service and before anything is signed, so an
    oversized or unreadable file costs no upload and leaves no row behind.
    """
    registered = await ingestion.register(
        user_id=user_id,
        filename=declaration.filename,
        content_type=declaration.content_type,
        byte_size=declaration.byte_size,
    )
    return MaterialUpload(
        **ingestion.presented(registered.material).model_dump(),
        upload_url=registered.upload_url,
    )


@router.post("/materials/{material_id}/complete", response_model=MaterialRead)
async def complete_upload(
    material: OwnedMaterial,
    user_id: CurrentUser,
    ingestion: IngestionServiceDep,
) -> MaterialRead:
    """The client reports the bytes landed, and we check before believing it.

    This is the moment a material becomes extractable, which is the moment it
    starts costing money — so the state it moves into is the one the sweep
    claims, and a claim with no object behind it is refused here rather than
    discovered by a model call that fails.
    """
    return ingestion.presented(
        await ingestion.mark_uploaded(material.id, user_id=user_id)
    )


@router.get("/materials/{material_id}", response_model=MaterialRead)
async def read_material(
    material: OwnedMaterial, ingestion: IngestionServiceDep
) -> MaterialRead:
    """One material, if it belongs to the caller.

    No upload URL. Re-signing on every read would turn a lookup into a fresh
    write capability against a material that may already hold an extracted deck.
    A thumbnail URL is a different thing and is issued here: it reads one
    downscaled first page, which is the artefact deliberately kept when the
    source document is destroyed.
    """
    return ingestion.presented(material)
