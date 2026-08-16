"""What survives a deck, and what does not.

This is the App Store answer (Open Risk #5), and it is a promise rather than an
optimisation: *"what survives is the extracted claims and a downscaled
first-page thumbnail"* (`docs/ingestion.md`). A deck is the most confidential
thing this product will ever hold, and the source document's only remaining jobs
after extraction — reprocessing and support debugging — were both knowingly
given up to be able to say that sentence and mean it.

So these tests are about an absence, which is the hardest thing to keep true.
Nothing breaks when a delete silently stops happening: extraction still works,
claims still ground the panel, and the only symptom is a bucket quietly filling
with other people's unannounced financials.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.modules.ingestion.schemas import MaterialState
from app.modules.ingestion.service import IngestionService
from tests.materials import MARGIN, FakeExtractionModel, extraction, reading, uploaded


def ingestion_with(db, storage) -> IngestionService:
    """The service against a substituted store, for the failure paths."""
    return IngestionService(db, storage=storage)
from tests.pdfs import minimal_pdf


async def test_the_deck_is_deleted_and_the_thumbnail_survives(
    db, ingestion, storage, account
):
    """The whole promise, in one pass. The claims are the deck now.

    Both halves together on purpose: a thumbnail stored without the source being
    deleted keeps the confidential document, and a source deleted without the
    thumbnail stored loses the one artefact the product is allowed to keep. Each
    half passing alone is a different broken promise.
    """
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(MARGIN))

    await extraction(db, storage, model).sweep()

    await db.refresh(material)
    assert material.state is MaterialState.READY
    assert await storage.get(material.storage_key) is None

    assert material.thumbnail_key is not None
    thumbnail = await storage.get(material.thumbnail_key)
    assert thumbnail is not None
    assert Image.open(io.BytesIO(thumbnail)).format == "JPEG"

    claims = await ingestion.claims(material.id, user_id=account.user_id)
    assert [claim.claim.metric for claim in claims] == ["gross margin"]


async def test_a_requeued_deck_keeps_its_bytes(db, ingestion, storage, account):
    """Deleting here would turn a busy minute into permanent data loss.

    A requeued material goes back to `pending` and will be claimed again, so its
    source is the only copy of a deck that is still going to be read. Purging on
    "extraction finished" rather than on "extraction finished *with*" is the one
    mistake in this area that cannot be recovered from — the user is told their
    deck is still being processed, and there is nothing left to process.
    """
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(complete=False, retryable=True))

    await extraction(db, storage, model).sweep()

    await db.refresh(material)
    assert material.state is MaterialState.PENDING
    assert material.source_deleted_at is None
    assert await storage.get(material.storage_key) is not None


async def test_a_failed_deck_does_not_keep_a_confidential_document(
    db, ingestion, storage, account
):
    """`failed` is terminal, so its bytes have no remaining reader.

    The user is told to re-upload rather than offered a retry, which means
    keeping the object is retaining somebody's unannounced financials for no
    purpose at all — the opposite of the trade this design made when it gave up
    reprocessing and support debugging to be able to promise deletion.
    """
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(complete=False, retryable=False))

    await extraction(db, storage, model).sweep()

    await db.refresh(material)
    assert material.state is MaterialState.FAILED
    assert material.source_deleted_at is not None
    assert await storage.get(material.storage_key) is None


async def test_a_deck_that_failed_still_has_a_thumbnail(
    db, ingestion, storage, account
):
    """Twenty kilobytes, and the difference between a row a user recognises and
    a grey rectangle beside the word "failed"."""
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(complete=False, retryable=False))

    await extraction(db, storage, model).sweep()

    await db.refresh(material)
    assert material.thumbnail_key is not None
    assert await storage.get(material.thumbnail_key) is not None


class RefusesToDelete:
    """The store, with its delete broken for a while.

    A wrapper rather than a fake store: everything else here — the presigned
    PUT, the real render, the real bytes — has to stay real, because what is
    under test is the recovery and not the plumbing.
    """

    def __init__(self, storage, *, failures: int = 1) -> None:
        self._storage = storage
        self._failures = failures
        self.attempts = 0

    def __getattr__(self, name):
        return getattr(self._storage, name)

    async def delete(self, key: str) -> None:
        self.attempts += 1
        if self._failures > 0:
            self._failures -= 1
            raise ConnectionError("the bucket had a bad afternoon")
        await self._storage.delete(key)


async def test_a_delete_that_fails_is_tried_again(db, ingestion, storage, account):
    """The promise survives one bad afternoon in the storage layer.

    Removing an object cannot join the transaction that settles the material, so
    a delete that fails has to be retried by something. Without that, a single
    503 leaves a confidential document in the bucket permanently, with nothing
    pointing at it and nothing to notice — the quietest way this promise could
    stop being true.
    """
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(MARGIN))
    broken = RefusesToDelete(storage)

    await extraction(db, broken, model).sweep()

    await db.refresh(material)
    assert material.state is MaterialState.READY
    assert material.source_deleted_at is None
    assert await storage.get(material.storage_key) is not None

    # A later pass, with the store answering again. Nothing had to be
    # rescheduled: the null timestamp is the whole of the retry state.
    await extraction(db, storage, model).sweep()

    await db.refresh(material)
    assert material.source_deleted_at is not None
    assert await storage.get(material.storage_key) is None


async def test_one_undeletable_object_does_not_strand_the_others(
    db, ingestion, storage, account, funded_account
):
    """A batch is not all-or-nothing, because the promise is about documents.

    If one object the store will not part with aborted the pass, every other
    user's deck would sit undeleted behind it — one stuck row turning a
    retention guarantee off for everybody.
    """
    stuck = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    other = await uploaded(ingestion, funded_account, minimal_pdf("Revenue up 40%"))
    model = FakeExtractionModel(reading(MARGIN))

    for _ in range(2):
        await extraction(db, storage, model).sweep()

    await db.refresh(stuck)
    await db.refresh(other)
    assert stuck.state is MaterialState.READY
    assert other.state is MaterialState.READY

    # Both are already purged by now, so re-run the purge against a store that
    # refuses the first delete it is handed, with both rows put back in scope.
    stuck.source_deleted_at = None
    other.source_deleted_at = None
    await db.commit()

    broken = RefusesToDelete(storage)
    purged = await ingestion_with(db, broken).purge_sources()

    assert broken.attempts == 2
    assert purged == 1
