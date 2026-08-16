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
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    AccountNotFound,
    ExtractionIncomplete,
    InvalidMaterialState,
    MaterialNotFound,
    MaterialNotReady,
    MaterialNotUploaded,
    MaterialTooLarge,
    UnsupportedMaterialType,
)
from app.core.logging import get_logger
from app.core.storage import ObjectStorage
from app.modules.billing.models import Account
from app.modules.billing.service import PERIOD_LENGTH
from app.modules.billing.tiers import (
    FREE_TIER_LIFETIME_PAGES,
    MAX_PAGES_PER_MATERIAL,
    MAX_UPLOAD_BYTES,
    MONTHLY_PAGE_BUDGET,
    UPGRADE_LADDER,
    next_tier_above,
    smallest_tier_accepting,
)
from app.modules.ingestion.extraction_model import ExtractedClaim, ExtractionResult
from app.modules.ingestion.models import ExtractionCost, Material, MaterialClaim
from app.modules.ingestion.parsing import THUMBNAIL_MEDIA_TYPE
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


def thumbnail_key_for(user_id: uuid.UUID, material_id: uuid.UUID) -> str:
    """Where a material's surviving first page lives.

    Its own prefix rather than a suffix under the source's key, because the two
    have opposite lifetimes: one is deleted minutes after it arrives and the
    other is what remains. A prefix is also the unit a bucket lifecycle rule
    operates on, which is how a tiered retention window would most naturally be
    expressed later.

    The owner is in the path here too, for the same reason as above.
    """
    return f"thumbnail/{user_id}/{material_id}"


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


#: How many retryable endings a material gets before it is failed.
#:
#: Generous on purpose. A rate limit is our capacity problem and not the user's
#: file, so a small budget would deliver exactly the data loss the failure
#: classifier exists to prevent — just an hour later. Ten attempts on the
#: backoff below spans a few hours, which is long enough to ride out any
#: throughput event we would not otherwise notice and alert on.
MAX_EXTRACTION_ATTEMPTS = 10

#: The first wait, doubled per attempt.
BACKOFF_BASE = timedelta(minutes=1)

#: The ceiling on that doubling. Without one, attempt ten waits over eight
#: hours — long past the point where a deck the user is waiting on has stopped
#: being useful to them.
BACKOFF_CAP = timedelta(minutes=30)


def _backoff(attempts: int) -> timedelta:
    """How long a requeued material waits before it may be claimed again.

    Exponential rather than linear, because backing off linearly against a rate
    limit is a slower stampede rather than a smaller one — every requeued deck
    returns together and spends the allowance in the same instant it recovered.
    """
    return min(BACKOFF_BASE * 2 ** (attempts - 1), BACKOFF_CAP)


def _pages_this_period():
    """Pages this material's owner has been billed for in their current window.

    Correlated against the row being considered, so it is one subquery inside
    the claim rather than a lookup per candidate.

    The window is the account's own entitlement period — the same clock the
    minutes allowance runs on — rather than a calendar month. A null
    `period_ends_at` means a tier that never renews, which is the free one, and
    the absence of a lower bound is exactly what makes its budget lifetime.

    A stale `period_ends_at` (a boundary passed, and `ensure_current_period` not
    yet run for that account) widens the window rather than narrowing it, so the
    error is a deck that waits rather than a budget that overspends. The next
    thing the user does that touches billing repairs it.
    """
    return (
        select(func.coalesce(func.sum(ExtractionCost.pages), 0))
        .where(
            ExtractionCost.user_id == Material.user_id,
            or_(
                Account.period_ends_at.is_(None),
                ExtractionCost.recorded_at >= Account.period_ends_at - PERIOD_LENGTH,
            ),
        )
        .correlate(Material, Account)
        .scalar_subquery()
    )


def _pages_today():
    """Pages billed in the last twenty-four hours, for the runaway ceiling.

    Rolling rather than calendar, which sidesteps the question of whose midnight
    and makes the release gradual — a calendar day would hold a runaway until
    a moment and then let all of it through at once.
    """
    return (
        select(func.coalesce(func.sum(ExtractionCost.pages), 0))
        .where(
            ExtractionCost.user_id == Material.user_id,
            ExtractionCost.recorded_at >= func.now() - timedelta(days=1),
        )
        .correlate(Material)
        .scalar_subquery()
    )


def _period_budget():
    """The owner's page budget, as SQL, built from the tier table itself.

    Generated from `MONTHLY_PAGE_BUDGET` rather than written out, so a tier
    added to pricing cannot be silently missing here — it falls to the free
    allowance, which throttles early and visibly instead of quietly granting
    unlimited extraction to whoever bought it.
    """
    return case(
        MONTHLY_PAGE_BUDGET,
        value=Account.entitlement_tier,
        else_=FREE_TIER_LIFETIME_PAGES,
    )


async def confirm_ready(
    db: AsyncSession, *, user_id: uuid.UUID, material_ids: Sequence[uuid.UUID]
) -> None:
    """Every one of these is the caller's and finished extracting, or raise.

    A module function rather than a method, because it is the one question
    another module asks about material and it needs none of what an
    `IngestionService` is built with — no object store, no presigning. Making
    `sessions` construct a storage client to ask whether a deck is ready would
    couple the session path to a bucket it never touches.

    It lives in `ingestion` all the same. Which states count as usable is
    ingestion's rule, and a copy of it inside `SessionService` is a copy that
    stops agreeing the day a sixth state appears.

    Not-yours and not-found are the same answer, as everywhere else here:
    distinguishing them tells a prober which material ids exist.
    """
    if not material_ids:
        return

    wanted = set(material_ids)
    rows = await db.execute(
        select(Material.id, Material.state).where(
            Material.id.in_(wanted), Material.user_id == user_id
        )
    )
    found = dict(rows.all())

    missing = wanted - found.keys()
    if missing:
        raise MaterialNotFound(
            material_id=str(sorted(map(str, missing))[0]), user_id=str(user_id)
        )

    for material_id, state in found.items():
        if state is MaterialState.READY:
            continue
        # Two messages, one refusal. A deck still extracting and a deck that
        # failed are the same answer to the room and opposite advice to the
        # person holding the phone.
        log.info(
            "session_material_not_ready",
            material_id=str(material_id),
            user_id=str(user_id),
            state=state.value,
        )
        raise MaterialNotReady(
            "That material could not be read. Please upload it again."
            if state is MaterialState.FAILED
            else None,
            material_id=str(material_id),
            user_id=str(user_id),
            state=state.value,
        )


class ClaimedMaterial(NamedTuple):
    """A material a sweep now holds, and the page cap it must be read under.

    The cap travels with the claim rather than being looked up by the caller,
    so the sweep never reads the tier table. Tier policy is billing's, and a
    second reader of it is a second place to forget that the free tier's budget
    is lifetime rather than monthly.
    """

    material: Material
    max_pages: int


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

    async def store_thumbnail(self, material: Material, thumbnail: bytes) -> None:
        """Keep the one page that outlives the document.

        Written as soon as the deck parses, rather than on success, so a
        material that fails extraction still has something to show in a list.
        It costs about twenty kilobytes and it is the difference between a
        failed upload the user recognises and a grey rectangle.

        Object first, row second. The other order would record a key pointing at
        nothing the moment a write failed — a broken image on every screen that
        shows this material, which is worse than a missing one because nothing
        would ever retry it. An orphan in the other direction is invisible and
        overwritten by the next attempt, since the key is derived rather than
        generated.
        """
        key = thumbnail_key_for(material.user_id, material.id)
        await self._storage.put(key, thumbnail, content_type=THUMBNAIL_MEDIA_TYPE)

        material.thumbnail_key = key
        await self._db.commit()

    async def purge_sources(self) -> int:
        """Delete the uploaded document of every material that is finished with it.

        The retention promise, and the reason it is a sweep rather than a line
        at the end of settlement: removing an object cannot join the transaction
        that settles the material — one is Postgres and the other an HTTP call
        to a bucket. So the row commits first and this runs after, which means a
        delete that fails is retried on the next pass instead of quietly leaving
        somebody's financials in a bucket forever.

        Only terminal materials. A requeued deck is going back to `pending` and
        still needs its bytes; deleting them would turn a rate limit into a deck
        that can never be read again — the exact data loss the whole classifier
        exists to prevent, arriving by a different route.

        `failed` counts as finished. It is terminal, the user is told to
        re-upload, and nothing will ever open that object again — so keeping it
        is retaining a confidential document for no purpose at all.

        Deleting an object that is already gone is not an error in S3, which is
        what makes the retry safe: a pass that deleted the object and then
        failed to commit simply deletes it again.
        """
        finished = await self._db.scalars(
            select(Material)
            .where(
                Material.state.in_((MaterialState.READY, MaterialState.FAILED)),
                Material.source_deleted_at.is_(None),
            )
            .with_for_update(skip_locked=True)
        )

        purged = 0
        for material in finished:
            try:
                await self._storage.delete(material.storage_key)
            except Exception:
                # Per material, and deliberately broad — the same call
                # `SweepRunner._guarded` makes, for the same reason. One object
                # the store will not part with must not stop every other
                # deletion in the batch, because the thing being protected here
                # is a promise about documents in general.
                #
                # Nothing is swallowed: the traceback is logged, the row keeps a
                # null `source_deleted_at` so the next pass tries again, and the
                # partial index this query runs on grows — which is the standing
                # signal that deletes are failing.
                log.exception(
                    "material_source_delete_failed",
                    material_id=str(material.id),
                    user_id=str(material.user_id),
                )
                continue

            material.source_deleted_at = func.now()
            purged += 1
            log.info(
                "material_source_deleted",
                material_id=str(material.id),
                user_id=str(material.user_id),
                state=material.state.value,
            )

        if purged:
            await self._db.commit()
        return purged

    async def release_stalled(self, *, timeout: timedelta) -> int:
        """Give back every deck held longer than a read can plausibly take.

        The crash-safety half of the claim. A process that dies mid-extraction
        leaves a row saying `extracting` with nothing behind it: no sweep will
        claim it, no user action can clear it, and the material simply never
        becomes ready. Same problem `finalizing` already solves for settlement —
        *"nothing separates 'finished settling' from 'died halfway'"* — and the
        same answer.

        Row by row rather than one `UPDATE`, following the reaper: a stalled
        claim is exceptional, the count is small, and the branch at the budget
        is far easier to read here than as a `CASE`.

        The attempt is counted even though a crash is not the file's fault. It
        is not free either — a deck that reliably kills the worker would
        otherwise be claimed forever, once per pass, in perpetuity.

        No backoff. Unlike a rate limit, a dead process says nothing about
        whether the next attempt will work, and the deck has already waited out
        the timeout.
        """
        stalled = await self._db.scalars(
            select(Material)
            .where(
                Material.state == MaterialState.EXTRACTING,
                Material.claimed_at < func.now() - timeout,
            )
            # Locked for the same reason the claim is. Every process runs this,
            # and two of them releasing the same row would each add one to
            # `attempts` — a deck that gives up on its budget twice as fast as
            # the number says, in proportion to how many workers are deployed.
            .with_for_update(skip_locked=True)
        )

        released = 0
        for material in stalled:
            material.attempts += 1
            material.claimed_at = None
            material.state = (
                MaterialState.FAILED
                if material.attempts >= MAX_EXTRACTION_ATTEMPTS
                else MaterialState.PENDING
            )
            released += 1
            log.warning(
                "material_extraction_released",
                material_id=str(material.id),
                user_id=str(material.user_id),
                attempts=material.attempts,
                state=material.state.value,
            )

        if released:
            await self._db.commit()
        return released

    async def claim_for_extraction(
        self, *, daily_page_ceiling: int
    ) -> ClaimedMaterial | None:
        """Take the oldest material waiting to be read, or nothing.

        `SKIP LOCKED` rather than idempotency, and the difference from the other
        sweeps is the whole reason this one needs a lock. The meter and the
        reaper derive what they owe from the database's clock, so two workers
        reach the same answer and the second one's writes are refused as
        duplicates. **A duplicate extraction is not a refused write, it is a
        second invoice** — so overlap is made impossible here rather than
        harmless.

        Oldest first, because the alternative is a queue where an unlucky deck
        can be passed over indefinitely while newer ones arrive.

        **Both page budgets are conditions of the claim, not checks after it.**
        A material left `pending` under an exhausted budget is a candidate on
        every pass until the window rolls, so refusing it afterwards would burn
        one of its ten retryable attempts each time and fail the deck hours
        before it was ever allowed to extract. As a condition it is skipped
        instead, and — because it is in the query rather than around it — one
        user with nothing left cannot sit at the head of the queue declining
        work for everybody else.

        The overshoot this accepts: the budget is compared against pages
        *already* billed, and a deck's own page count is not knowable until it
        has been parsed. So a user one page under can extract a full deck and
        land over. It is bounded by `MAX_PAGES_PER_MATERIAL` — 300 at the top
        rung, on a 1200-page budget — and closing it exactly would mean parsing
        every deck before deciding whether it was allowed to be parsed.
        """
        claimed = (
            await self._db.execute(
                select(Material, Account.entitlement_tier)
                .join(Account, Account.user_id == Material.user_id)
                .where(
                    Material.state == MaterialState.PENDING,
                    # The backoff a requeue wrote. Filtered here rather than
                    # slept off in the worker, because the worker that would
                    # sleep is the one every other deck is waiting on — and
                    # forgetting it makes the wait decoration: a rate-limited
                    # deck comes straight back on the next pass, into the limit
                    # that caused it. Nothing else fails when it is missed.
                    or_(
                        Material.retry_at.is_(None),
                        Material.retry_at <= func.now(),
                    ),
                    _pages_this_period() < _period_budget(),
                    _pages_today() < daily_page_ceiling,
                )
                .order_by(Material.created_at)
                .limit(1)
                .with_for_update(skip_locked=True, of=Material)
            )
        ).first()

        if claimed is None:
            return None

        material, tier = claimed
        material.state = MaterialState.EXTRACTING
        # The database's clock, because the stale-claim query compares it
        # against the database's clock. A worker with a skewed clock would
        # otherwise either hold a deck forever or have it taken back mid-read.
        material.claimed_at = func.now()
        await self._db.commit()
        # The claim mark was written as SQL, so the in-memory value is still the
        # expression until it is read back. Cheap — once per pass — and it keeps
        # the returned row honest for anything that inspects it.
        await self._db.refresh(material)

        log.info(
            "material_claimed",
            material_id=str(material.id),
            user_id=str(material.user_id),
            tier=tier,
            attempts=material.attempts,
        )
        return ClaimedMaterial(material, MAX_PAGES_PER_MATERIAL[tier])

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
        self, material_id: uuid.UUID, *, result: ExtractionResult | None = None
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

    async def requeue_extraction(
        self, material_id: uuid.UUID, *, result: ExtractionResult | None = None
    ) -> Material:
        """Put a deck back in the queue, later, and record what it already cost.

        The third ending, and the one that keeps a capacity problem from
        becoming data loss. `pending` *is* the queue, so requeueing is one
        `UPDATE` — no broker, no second source of truth about what work exists.

        The wait is written on the row rather than slept off in the worker,
        because the worker that would sleep is the one every other deck is
        waiting on.

        A budget still exists, because a deck that times out on every attempt
        for a day is not going to start working and must not be claimed forever.
        It is deliberately generous: a rate limit is our capacity problem and
        not the user's file, so giving up early is the failure this method was
        built to prevent, arriving late instead.
        """
        material = await self._claimed(material_id)
        material.attempts += 1

        if material.attempts >= MAX_EXTRACTION_ATTEMPTS:
            log.warning(
                "material_extraction_gave_up",
                material_id=str(material.id),
                user_id=str(material.user_id),
                attempts=material.attempts,
            )
            return await self._close(
                material, result, state=MaterialState.FAILED, claims=0
            )

        return await self._close(
            material,
            result,
            state=MaterialState.PENDING,
            claims=0,
            retry_after=_backoff(material.attempts),
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
        result: ExtractionResult | None,
        *,
        state: MaterialState,
        claims: int,
        retry_after: timedelta | None = None,
    ) -> Material:
        """The cost row and the state move, in one transaction.

        Shared by all three endings because they are the same write with a
        different final state. Splitting them would be three places to remember
        that a cost row is owed, and the one that gets forgotten is the failure
        path — where the money is least visible and most easily denied.
        """
        tier = await self._tier_of(material.user_id)
        # `None` is an attempt that ended before a model was reached at all — a
        # deck over the tier's page cap, an object that vanished, a store having
        # a bad day. There is nothing to bill and nothing to report but the
        # ending itself.
        spent = result is not None and (
            result.usage.input_tokens or result.usage.output_tokens
        )

        if result is not None and spent:
            # `docs/ingestion.md`: *"`extraction_costs` records work
            # performed."* An attempt refused before anything was billed —
            # every call rate-limited, a credential rejected — describes no
            # work, and a row per failed sweep pass would bury the rows that do.
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
        # Cleared on every ending but a requeue. A stale wait on a `ready` or
        # `failed` row means nothing, and a wait left behind on a row that is
        # about to be claimed again would be honoured a second time.
        material.retry_at = (
            datetime.now(UTC) + retry_after if retry_after else None
        )
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
            pages=result.usage.pages if result else 0,
            calls=result.usage.calls if result else 0,
            claims=claims,
            dropped=result.dropped if result else 0,
            corrected=result.corrected if result else 0,
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
