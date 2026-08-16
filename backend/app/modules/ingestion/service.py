"""Material lifecycle.

Business logic lives here and never in the router (CLAUDE.md). The state machine
is `docs/ingestion.md`; what this module owns is that a material only ever moves
between adjacent states, that nothing becomes extractable before its bytes have
arrived, and that a file too large for the caller's plan is refused before a URL
exists to send it to.
"""

from __future__ import annotations

import math
import uuid
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    AccountNotFound,
    InvalidMaterialState,
    MaterialNotFound,
    MaterialNotUploaded,
    MaterialTooLarge,
    UnsupportedMaterialType,
)
from app.core.logging import get_logger
from app.core.storage import ObjectStorage
from app.modules.billing.models import Account
from app.modules.billing.tiers import (
    MAX_PAGES_PER_MATERIAL,
    MAX_UPLOAD_BYTES,
    UPGRADE_LADDER,
    next_tier_above,
    smallest_tier_accepting,
)
from app.modules.ingestion.models import Material
from app.modules.ingestion.schemas import (
    ACCEPTED_CONTENT_TYPES,
    MaterialLimits,
    MaterialState,
    TierUpload,
)

log = get_logger(__name__, tag="ingestion")

MB = 1024 * 1024


def storage_key_for(user_id: uuid.UUID, material_id: uuid.UUID) -> str:
    """Where a material's bytes live.

    Derived, never supplied by the caller: a caller who chooses the key is a
    caller who can choose somebody else's. The owner is in the path as well as
    on the row, so a mistake in the read path has to get two things wrong at
    once before it serves one account's deck to another.
    """
    return f"material/{user_id}/{material_id}"


def megabytes(byte_size: int, *, round_up: bool = False) -> str:
    """A size a person can compare against a tier card.

    `round_up` for the file and not for the cap, which is the only way the two
    halves of a refusal cannot contradict each other. A file one byte over a
    10MB cap rounds down to "10 MB" and produces *"That file is 10 MB. Your plan
    accepts up to 10 MB"* — a message that reads as a bug and invites a support
    ticket rather than an upgrade.
    """
    tenths = byte_size / MB * 10
    value = (math.ceil if round_up else round)(tenths) / 10
    return f"{value:g} MB"


class RegisteredUpload(NamedTuple):
    """A material and the single URL that may fill it.

    Returned together because they are one act. Splitting them would make it
    possible to register a material and never sign anything, which is a row the
    reaper has to clean up for no reason.
    """

    material: Material
    upload_url: str


class IngestionService:
    """Materials, from presign through to extracted claims."""

    def __init__(self, db: AsyncSession, *, storage: ObjectStorage) -> None:
        self._db = db
        self._storage = storage

    async def limits(self, *, user_id: uuid.UUID) -> MaterialLimits:
        """What this caller may upload, and what the next rung would allow.

        Read by the app before any file is chosen, so it can refuse locally with
        no round trip. The server refusal in `register` stays the real wall —
        this is the copy of the tier table that keeps the app from holding its
        own, where a pricing change would ship as an app release.
        """
        tier = await self._tier_of(user_id)
        upgrade = next_tier_above(tier)

        return MaterialLimits(
            **self._tier_upload(tier).model_dump(),
            accepted_content_types=sorted(ACCEPTED_CONTENT_TYPES),
            upgrade=self._tier_upload(upgrade) if upgrade else None,
        )

    async def register(
        self,
        *,
        user_id: uuid.UUID,
        filename: str,
        content_type: str,
        byte_size: int,
    ) -> RegisteredUpload:
        """Create the row a presigned upload will be signed against.

        Both refusals happen before anything is written or signed, so a rejected
        file costs the user no upload and leaves us no row to reap.

        The material is deliberately not extractable yet. The object does not
        exist at this point — only somewhere for it to go — and a sweep that
        claimed this row would pay a model to read nothing.

        The filename is not logged. It is user-supplied text about a
        confidential document, and CLAUDE.md's rule against logging ingested
        material contents is not honoured by a line reading
        `acquisition-terms-final.pdf`.
        """
        if content_type not in ACCEPTED_CONTENT_TYPES:
            log.warning(
                "material_type_refused",
                user_id=str(user_id),
                content_type=content_type,
            )
            raise UnsupportedMaterialType(
                user_id=str(user_id), content_type=content_type
            )

        tier = await self._tier_of(user_id)
        cap = MAX_UPLOAD_BYTES[tier]
        if byte_size > cap:
            raise self._too_large(
                user_id=user_id, tier=tier, byte_size=byte_size, cap=cap
            )

        material_id = uuid.uuid4()
        material = Material(
            id=material_id,
            user_id=user_id,
            state=MaterialState.AWAITING_UPLOAD,
            filename=filename,
            content_type=content_type,
            byte_size=byte_size,
            storage_key=storage_key_for(user_id, material_id),
        )

        self._db.add(material)
        await self._db.commit()

        log.info(
            "material_registered",
            material_id=str(material_id),
            user_id=str(user_id),
            content_type=content_type,
            byte_size=byte_size,
        )
        return RegisteredUpload(
            material=material,
            # Signed with the declared size and type, which makes both binding:
            # the store refuses a body that disagrees, so the tier cap above is
            # a property of the upload rather than a check we did once.
            upload_url=self._storage.presign_put(
                material.storage_key,
                content_length=byte_size,
                content_type=content_type,
            ),
        )

    async def mark_uploaded(
        self, material_id: uuid.UUID, *, user_id: uuid.UUID
    ) -> Material:
        """The client says the bytes landed, so the extractor may have it.

        This is the moment a material starts costing money — `pending` is the
        one state the sweep claims — which is why it is a deliberate call rather
        than something inferred from the row ageing, and why the claim is
        checked against the store rather than believed.
        """
        material = await self.get(material_id, user_id=user_id)

        if material.state is not MaterialState.AWAITING_UPLOAD:
            raise InvalidMaterialState(
                material_id=str(material_id), state=material.state.value
            )

        if not await self._storage.exists(material.storage_key):
            log.warning(
                "material_completion_without_object",
                material_id=str(material_id),
                user_id=str(user_id),
            )
            raise MaterialNotUploaded(
                material_id=str(material_id), user_id=str(user_id)
            )

        material.state = MaterialState.PENDING
        await self._db.commit()

        log.info(
            "material_uploaded", material_id=str(material_id), user_id=str(user_id)
        )
        return material

    async def get(self, material_id: uuid.UUID, *, user_id: uuid.UUID) -> Material:
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

    async def _tier_of(self, user_id: uuid.UUID) -> str:
        """The caller's entitlement tier.

        A column on a row the request already touches, which is the whole cost
        of publishing per-tier caps — the upload path is no longer a pure
        function of the file.
        """
        tier = await self._db.scalar(
            select(Account.entitlement_tier).where(Account.user_id == user_id)
        )
        if tier is None:
            raise AccountNotFound(user_id=str(user_id))
        return tier

    @staticmethod
    def _tier_upload(tier: str) -> TierUpload:
        return TierUpload(
            tier=tier,
            max_upload_bytes=MAX_UPLOAD_BYTES[tier],
            max_pages_per_material=MAX_PAGES_PER_MATERIAL[tier],
        )

    @staticmethod
    def _too_large(
        *, user_id: uuid.UUID, tier: str, byte_size: int, cap: int
    ) -> MaterialTooLarge:
        """Assemble the refusal, in the tone the product settled on.

        Fact, then the fix: the file's size, the plan's cap, and the cheapest
        tier that would take it. No apology and no verb of persuasion — the
        upgrade is stated as an available fact, and the client draws the button
        beside it. When nothing on sale would accept the file, the last sentence
        is the ceiling rather than an offer, because selling a plan that still
        refuses the upload is the one thing this refusal may not do.

        Logged as the denial it is (CLAUDE.md), with the tier and the size — the
        two facts that answer "should this cap move" when it turns out real
        decks are bigger than the number we guessed.
        """
        offer = smallest_tier_accepting(byte_size)
        top = MAX_UPLOAD_BYTES[UPGRADE_LADDER[-1]]
        tail = (
            f"{offer.capitalize()} accepts up to {megabytes(MAX_UPLOAD_BYTES[offer])}."
            if offer
            else f"The largest file we accept is {megabytes(top)}."
        )

        log.warning(
            "material_size_refused",
            user_id=str(user_id),
            tier=tier,
            byte_size=byte_size,
            cap_bytes=cap,
            offer_tier=offer,
        )
        return MaterialTooLarge(
            f"That file is {megabytes(byte_size, round_up=True)}. "
            f"Your plan accepts up to {megabytes(cap)}. {tail}",
            user_id=str(user_id),
            tier=tier,
            byte_size=byte_size,
        )
