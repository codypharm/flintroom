"""The extraction sweep — one pass, one deck.

The loop nobody asks for. Everything before this slice was reachable only by
hand: a material could be registered, uploaded and settled, and nothing in the
running process ever moved one from `pending` to `ready`.

**One material per pass, and that number is the fleet's real concurrency
ceiling.** The adapter reads a deck four calls at a time, but that semaphore
bounds one *material* — the API key is one credential for the whole deployment,
so fifty decks at four calls each is two hundred concurrent requests against a
rate limit that has no idea whose deck is whose (`docs/ingestion.md`). Holding
one deck per process makes the ceiling `processes × extraction_concurrent_calls`,
which is a number that can be reasoned about, rather than one that is discovered
as a wall of 429s.

No SQL lives here. Claiming, releasing and the three endings are all
`IngestionService` methods, so this file is the order things happen in and
nothing else.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import MaterialTooManyPages, MaterialUnreadable
from app.core.logging import get_logger
from app.core.storage import ObjectStorage
from app.modules.ingestion.extraction_model import ExtractionModel
from app.modules.ingestion.parsing import parse
from app.modules.ingestion.service import IngestionService

log = get_logger(__name__, tag="ingestion")

#: How long a deck may be held before we assume nothing is holding it.
#:
#: Sized against the slowest legitimate read rather than the average one. A
#: pro-tier 300-page deck is fifteen model calls at four in flight, so four
#: waves of a call that may itself retry four times with backoff — minutes, and
#: the parse before it is a CPU-bound render of every page.
#:
#: Erring long is deliberate and the asymmetry is not close. Too short takes a
#: deck back while its calls are still in flight, and one deck becomes two
#: invoices — the exact duplication the claim exists to prevent. Too long leaves
#: a crashed extraction waiting a few extra minutes for a user who has already
#: been told it is being read.
EXTRACTION_TIMEOUT = timedelta(minutes=15)

#: Pages one account may extract in a rolling day when nothing configures it.
#:
#: A circuit breaker against a loop, a bug or a script — not an entitlement, and
#: uniform across tiers for that reason. `Settings.daily_page_ceiling` is where
#: a deployment overrides it, which is the point: this is a number to turn down
#: at 3am rather than one to ship a release for.
#:
#: It may never fall below the largest `MAX_PAGES_PER_MATERIAL`, or a plan
#: refuses to extract a file it sold — see `Settings.daily_page_ceiling` for
#: the case that caught it, and `test_material_limits.py` for the guard.
DEFAULT_DAILY_PAGE_CEILING = 600


class ExtractionService:
    """Reads one waiting deck, and decides how the attempt ended."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        storage: ObjectStorage,
        model: ExtractionModel,
        daily_page_ceiling: int = DEFAULT_DAILY_PAGE_CEILING,
    ) -> None:
        self._ingestion = IngestionService(db, storage=storage)
        self._storage = storage
        self._model = model
        self._daily_page_ceiling = daily_page_ceiling

    async def sweep(self) -> bool:
        """One pass. True if a deck was read, so the loop can pace itself.

        The return value is not a status — it is what lets the runner come
        straight back while there is a queue and idle politely when there is
        not, without a second query asking whether there is work.

        Four steps, and the order of the outer ones is load-bearing. Releasing
        stalled claims first makes a deck stranded by a dead worker a candidate
        for *this* pass rather than the next one. Purging last means the deck
        this pass just finished has its source deleted before the pass returns —
        a promise kept immediately rather than one that depends on another pass
        ever happening.

        The purge runs whether or not a deck was read, which is what makes it
        the recovery path as well as the fast one: a delete that failed leaves
        the material undeleted, and an idle loop keeps trying it.

        Destroyed materials are purged last, after the deck this pass read has
        finished — so a user who deletes a deck while it is being extracted has
        the row gone by the end of the same pass rather than the next one.
        """
        await self._ingestion.release_stalled(timeout=EXTRACTION_TIMEOUT)
        worked = await self._read_one()
        await self._ingestion.purge_sources()
        await self._ingestion.purge_deleted()
        return worked

    async def _read_one(self) -> bool:
        """Claim a waiting deck and take it to one of its endings."""
        claimed = await self._ingestion.claim_for_extraction(
            daily_page_ceiling=self._daily_page_ceiling
        )
        if claimed is None:
            return False

        material = claimed.material
        data = await self._storage.get(material.storage_key)

        if data is None:
            # The handshake HEADs the store before queueing, so this is rare —
            # but an object can go between then and here, and nothing about
            # waiting brings a deleted one back. Retrying would spend ten
            # attempts over several hours to reach the same answer.
            log.error(
                "material_object_missing",
                material_id=str(material.id),
                user_id=str(material.user_id),
            )
            await self._ingestion.fail_extraction(material.id)
            return True

        try:
            parsed = await parse(
                data,
                content_type=material.content_type,
                max_pages=claimed.max_pages,
            )
        except (MaterialTooManyPages, MaterialUnreadable):
            # Both terminal, and both decided before a model is reached. No
            # window rolls over into a file being shorter or a corrupt PDF
            # repairing itself, so `pending` would mean this deck is claimed by
            # every pass forever, failing identically each time.
            #
            # The refusals themselves are already logged where they are raised,
            # with the counts a user needs to send a smaller file.
            await self._ingestion.fail_extraction(material.id)
            return True

        # Asked here because everything below this line either writes an object
        # or spends money, and both are wrong for a deck the user destroyed while
        # we had it open — which is the most likely moment for anyone to destroy
        # one. A thumbnail rendered after the deletion would be an object with no
        # row pointing at it, which nothing would ever find to clean up.
        if await self._ingestion.abandon_if_deleted(material.id):
            return True

        # Before the model call, because it is the artefact that survives
        # whatever the model says next — including a deck that never reads.
        await self._ingestion.store_thumbnail(material, parsed.thumbnail)

        result = await self._model.extract(parsed.pages)
        await self._end(material.id, result)
        return True

    async def _end(self, material_id: uuid.UUID, result) -> None:
        """Which of the three endings this attempt earned.

        The adapter never raises — it answers `complete` and `retryable`, and
        this is the one place those two are read. Written as three named calls
        rather than a state variable because they are three different promises:
        `ready` says the panel may ground itself on this, `failed` says
        re-upload, and `pending` says nothing at all yet.

        `retryable` decides the difference between the last two, and it is
        decided by *why* calls failed rather than by how many — see
        `_merged` in the adapter.
        """
        if result.complete:
            await self._ingestion.settle_extraction(material_id, result=result)
        elif result.retryable:
            await self._ingestion.requeue_extraction(material_id, result=result)
        else:
            await self._ingestion.fail_extraction(material_id, result=result)
