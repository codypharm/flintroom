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
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    AccountNotFound,
    ExtractionIncomplete,
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
from app.modules.ingestion.extraction_model import ExtractedClaim, ExtractionResult
from app.modules.ingestion.models import ExtractionCost, Material, MaterialClaim
from app.modules.ingestion.schemas import (
    ACCEPTED_CONTENT_TYPES,
    AssertionClaim,
    ClaimKind,
    MaterialLimits,
    MaterialState,
    QuantitativeClaim,
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


def _claim_row(material: Material, extracted: ExtractedClaim) -> MaterialClaim:
    """One extracted claim, as the row that outlives the document.

    The kind is dispatched on explicitly and an unhandled one raises. A third
    claim kind added to the union would otherwise land in the `else` branch and
    be written as an assertion — a silent corruption that the CHECK constraint
    could not catch, because the row it produced would be a perfectly valid
    assertion.
    """
    claim = extracted.claim
    row = MaterialClaim(
        material_id=material.id,
        user_id=material.user_id,
        page=extracted.page,
        kind=claim.kind,
        quote=claim.quote,
        quote_verified=extracted.quote_verified,
    )

    if isinstance(claim, QuantitativeClaim):
        row.metric = claim.metric
        # Via `str`, not `Decimal(float)`. The float already holds whatever
        # binary approximation it holds; going through its shortest repr is what
        # puts 61.1 in the column instead of 61.099999999999994049...
        row.value = Decimal(str(claim.value))
        row.unit = claim.unit
        row.period = claim.period
    elif isinstance(claim, AssertionClaim):
        row.subject = claim.subject
        row.statement = claim.statement
    else:
        raise ValueError(f"no column mapping for claim kind {claim.kind}")

    return row


def _extracted_claim(row: MaterialClaim) -> ExtractedClaim:
    """A row, back as the typed claim the Auditor can compare."""
    claim: QuantitativeClaim | AssertionClaim
    if row.kind is ClaimKind.QUANTITATIVE:
        claim = QuantitativeClaim(
            quote=row.quote,
            metric=row.metric,
            value=float(row.value),
            unit=row.unit,
            period=row.period,
        )
    elif row.kind is ClaimKind.ASSERTION:
        claim = AssertionClaim(
            quote=row.quote, subject=row.subject, statement=row.statement
        )
    else:
        raise ValueError(f"no claim type for kind {row.kind}")

    return ExtractedClaim(
        page=row.page, claim=claim, quote_verified=row.quote_verified
    )


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

    async def settle_extraction(
        self, material_id: uuid.UUID, *, result: ExtractionResult
    ) -> Material:
        """Write what a model found, what it cost, and close the material.

        One transaction, deliberately. The claims, the cost row and the state
        move are the same fact — a material that is `ready` with no claims is a
        deck the panel will silently ground nothing against, and a cost row
        without a settled material is money attributed to work that gets done
        again.

        No `user_id` parameter. The caller is the extraction sweep, which is
        SYSTEM rather than a request — and the owner is on the row, which is a
        better authority than anything a background worker could pass in.

        Nothing here is logged with content. Quotes, metrics and statements are
        ingested material contents, forbidden in logs by CLAUDE.md and, unlike a
        secret, not detectable by key name — so counts go to the log and text
        does not.
        """
        if not result.complete:
            # Before the row is even loaded. A deck read in fifteen calls can
            # lose one of them, and `ready` is the promise the panel grounds
            # itself on — the source document is deleted on success, so a
            # partially-stored deck is a gap nothing can find later.
            raise ExtractionIncomplete(material_id=str(material_id))

        material = await self._claimed(material_id)

        for extracted in result.claims:
            self._db.add(_claim_row(material, extracted))

        return await self._close(
            material, result, state=MaterialState.READY, claims=len(result.claims)
        )

    async def fail_extraction(
        self, material_id: uuid.UUID, *, result: ExtractionResult
    ) -> Material:
        """Record what a failed attempt cost, and stop trying.

        The twin of `settle_extraction`, and the reason the adapter returns an
        incomplete result rather than raising: a deck read in several calls can
        lose one after the others have already been billed. Those calls are on
        the invoice whether or not their answers were usable, and §4.3 measures
        margin against observed spend — cost that cannot be reconciled is worse
        than cost that was wasted.

        No claims are written, whatever the result carries. Failing is not a
        quieter way of storing part of a deck.

        `failed` is terminal. A material that could not be read is re-uploaded
        rather than retried in place, which is a separate decision from a
        provider being unreachable — that case never reaches here, because the
        adapter raises and the sweep leaves the material `pending`.
        """
        material = await self._claimed(material_id)
        return await self._close(
            material, result, state=MaterialState.FAILED, claims=0
        )

    async def _claimed(self, material_id: uuid.UUID) -> Material:
        """The material a sweep is holding, or a refusal.

        Requiring `extracting` is what stops two workers settling the same
        material — and what stops a settle arriving for a deck nobody extracted.
        """
        material = await self._db.get(Material, material_id)
        if material is None:
            raise MaterialNotFound(material_id=str(material_id))

        if material.state is not MaterialState.EXTRACTING:
            raise InvalidMaterialState(
                material_id=str(material_id), state=material.state.value
            )
        return material

    async def _close(
        self,
        material: Material,
        result: ExtractionResult,
        *,
        state: MaterialState,
        claims: int,
    ) -> Material:
        """The cost row and the state move, in one transaction.

        Shared by both endings because they are the same write with a different
        final state. Splitting them would be two places to remember that a cost
        row is owed, and the one that gets forgotten is the failure path — where
        the money is least visible and most easily denied.
        """
        tier = await self._tier_of(material.user_id)

        self._db.add(
            ExtractionCost(
                material_id=material.id,
                user_id=material.user_id,
                tier=tier,
                provider=result.usage.provider,
                model=result.usage.model,
                pages=result.usage.pages,
                calls=result.usage.calls,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                claims_recorded=claims,
                claims_dropped=result.dropped,
                pages_corrected=result.corrected,
            )
        )

        material.state = state
        # The claim mark and `extracting` are one fact, and a CHECK constraint
        # says so. Clearing it is not tidying up — leaving it would fail the
        # write.
        material.claimed_at = None

        await self._db.commit()

        log.info(
            "material_extraction_closed",
            material_id=str(material.id),
            user_id=str(material.user_id),
            tier=tier,
            state=state.value,
            pages=result.usage.pages,
            calls=result.usage.calls,
            claims=claims,
            dropped=result.dropped,
            corrected=result.corrected,
        )
        return material

    async def claims(
        self, material_id: uuid.UUID, *, user_id: uuid.UUID
    ) -> list[ExtractedClaim]:
        """Everything this material asserts, in reading order.

        Returned as the same typed claims the extraction produced rather than as
        rows, because the Auditor compares a slide's figure against a spoken one
        and the comparison lives on the type. A caller handed ORM rows would
        have to rebuild `comparable_to` by hand, and the first one to get it
        slightly wrong invents an agreement between figures that never agreed.

        Ownership is checked by loading the material through `get`, so a
        material id belonging to somebody else is a 404 here for the same reason
        it is one there.
        """
        await self.get(material_id, user_id=user_id)

        rows = await self._db.scalars(
            select(MaterialClaim)
            .where(MaterialClaim.material_id == material_id)
            .order_by(MaterialClaim.page, MaterialClaim.created_at)
        )
        return [_extracted_claim(row) for row in rows]

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
