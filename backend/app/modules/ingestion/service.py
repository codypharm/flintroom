"""Material lifecycle.

Business logic lives here and never in the router (CLAUDE.md). The state machine
is `docs/ingestion.md`; what this module owns is that a material only ever moves
between adjacent states, and that nothing becomes extractable before its bytes
have arrived.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidMaterialState, MaterialNotFound
from app.core.logging import get_logger
from app.modules.ingestion.models import Material
from app.modules.ingestion.schemas import MaterialState

log = get_logger(__name__, tag="ingestion")


def storage_key_for(user_id: uuid.UUID, material_id: uuid.UUID) -> str:
    """Where a material's bytes live.

    Derived, never supplied by the caller: a caller who chooses the key is a
    caller who can choose somebody else's. The owner is in the path as well as
    on the row, so a mistake in the read path has to get two things wrong at
    once before it serves one account's deck to another.
    """
    return f"material/{user_id}/{material_id}"


class IngestionService:
    """Materials, from presign through to extracted claims."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def register(
        self,
        *,
        user_id: uuid.UUID,
        filename: str,
        content_type: str,
    ) -> Material:
        """Create the row a presigned upload will be signed against.

        Deliberately not extractable yet. The object does not exist at this
        point — only somewhere for it to go — and a sweep that claimed this row
        would pay a model to read nothing.

        The filename is not logged. It is user-supplied text about a
        confidential document, and CLAUDE.md's rule against logging ingested
        material contents is not honoured by a line reading
        `acquisition-terms-final.pdf`.
        """
        material_id = uuid.uuid4()
        material = Material(
            id=material_id,
            user_id=user_id,
            state=MaterialState.AWAITING_UPLOAD,
            filename=filename,
            content_type=content_type,
            storage_key=storage_key_for(user_id, material_id),
        )

        self._db.add(material)
        await self._db.commit()

        log.info(
            "material_registered",
            material_id=str(material_id),
            user_id=str(user_id),
            content_type=content_type,
        )
        return material

    async def mark_uploaded(
        self, material_id: uuid.UUID, *, user_id: uuid.UUID
    ) -> Material:
        """The client says the bytes landed, so the extractor may have it.

        This is the moment a material starts costing money — `pending` is the
        one state the sweep claims — which is why it is a deliberate call rather
        than something inferred from the row ageing.
        """
        material = await self._owned(material_id, user_id=user_id)

        if material.state is not MaterialState.AWAITING_UPLOAD:
            raise InvalidMaterialState(
                material_id=str(material_id), state=material.state.value
            )

        material.state = MaterialState.PENDING
        await self._db.commit()

        log.info(
            "material_uploaded", material_id=str(material_id), user_id=str(user_id)
        )
        return material

    async def _owned(self, material_id: uuid.UUID, *, user_id: uuid.UUID) -> Material:
        """The caller's material, or `MaterialNotFound`.

        Ownership is part of the lookup rather than a check after it. A separate
        check is one a future caller can forget, and the failure mode is another
        account's deck. Not-found and not-yours are the same answer on purpose:
        distinguishing them tells a prober which material ids exist.
        """
        material = await self._db.scalar(
            select(Material).where(
                Material.id == material_id, Material.user_id == user_id
            )
        )
        if material is None:
            raise MaterialNotFound(material_id=str(material_id), user_id=str(user_id))
        return material
