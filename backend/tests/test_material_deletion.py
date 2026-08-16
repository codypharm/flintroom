"""Deleting a material, which until now the retention rule only promised.

`material_claims` says extracted claims are kept *"until the user deletes the
Material"* — a sentence describing something a user could not do, which is the
worst kind of retention policy: one that reads correctly and is unenforceable.

What deletion has to be true of, in order of how quietly each can break:

- The bytes go, both of them. The source is usually already gone by extraction,
  so the thumbnail is the object this endpoint is actually responsible for.
- The claims go with it. They *are* the deck by then — a deck's figures outliving
  the deck is the same disclosure one step removed.
- `extraction_costs` stays. It has no foreign key precisely so that "upload,
  extract, delete, repeat" cannot erase its own trail.
- A room that is still running does not lose its grounding underneath it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.actors import ActorContext
from app.modules.auth.tokens import AccessTokens
from app.modules.audit_log.models import AuditEvent
from app.modules.audit_log.schemas import AuditEventType
from app.modules.billing.models import Account
from app.modules.ingestion.models import ExtractionCost, Material, MaterialClaim
from app.modules.ingestion.schemas import MaterialState
from app.modules.ingestion.service import IngestionService
from app.modules.sessions.schemas import EndReason
from tests.conftest import SECRET
from tests.materials import (
    MARGIN,
    FakeExtractionModel,
    claim,
    extracted,
    extraction,
    reading,
    uploaded,
)
from tests.pdfs import minimal_pdf
from tests.test_retention import RefusesToDelete


@pytest.fixture
def bearer():
    """Headers that authenticate as a given user."""

    def headers(user_id: uuid.UUID) -> dict[str, str]:
        token = AccessTokens(secret=SECRET).issue(user_id=user_id)
        return {"Authorization": f"Bearer {token}"}

    return headers


def deleting(db, storage, account) -> IngestionService:
    """Ingestion as the endpoint builds it — attributed to the account holder."""
    return IngestionService(
        db, storage=storage, actor=ActorContext.user(account.user_id)
    )


async def rows(db, material_id) -> tuple[Material | None, int]:
    """The material and how many claims still point at it."""
    material = await db.scalar(select(Material).where(Material.id == material_id))
    claims = await db.scalars(
        select(MaterialClaim).where(MaterialClaim.material_id == material_id)
    )
    return material, len(list(claims))


async def test_deleting_a_deck_takes_its_thumbnail_and_its_claims_with_it(
    db, ingestion, storage, account
):
    """The tracer bullet, and the whole of what deletion means.

    The claims are asserted gone as deliberately as the object is. By this point
    they are the only surviving representation of the document — keeping them
    after the user asked for the deck to go would be retaining the figures out of
    somebody's unannounced board deck, which is what they came to delete.
    """
    material = await extracted(db, ingestion, storage, account)
    thumbnail_key = material.thumbnail_key
    assert (await rows(db, material.id))[1] == 1

    await deleting(db, storage, account).delete(material.id, user_id=account.user_id)

    assert await storage.get(thumbnail_key) is None

    await extraction(db, storage, FakeExtractionModel()).sweep()

    material_row, claims = await rows(db, material.id)
    assert material_row is None
    assert claims == 0


async def test_a_deleted_deck_is_already_gone_from_the_api(
    client, db, ingestion, storage, account, bearer
):
    """204, and the next read is a 404 — no waiting for a sweep to catch up.

    The row survives the request by seconds so that a worker mid-extraction has
    something to write its cost row against, but that is our bookkeeping and not
    a window in which the user's deck still exists to them.
    """
    material = await extracted(db, ingestion, storage, account)
    headers = bearer(account.user_id)

    deleted = await client.delete(f"/v1/materials/{material.id}", headers=headers)

    assert deleted.status_code == 204, deleted.text
    read = await client.get(f"/v1/materials/{material.id}", headers=headers)
    assert read.status_code == 404
    assert read.json()["error"]["code"] == "material_not_found"


async def test_deleting_twice_is_a_404_rather_than_a_500(
    client, db, ingestion, storage, account, bearer
):
    """The duplicate-action edge case, answered the way the table requires.

    A double-tap on a slow connection is the ordinary way this happens, and the
    row is still there for the few seconds between the mark and the purge — so
    without the filter the second call would find it and try to delete it again.
    """
    material = await extracted(db, ingestion, storage, account)
    headers = bearer(account.user_id)

    first = await client.delete(f"/v1/materials/{material.id}", headers=headers)
    second = await client.delete(f"/v1/materials/{material.id}", headers=headers)

    assert first.status_code == 204
    assert second.status_code == 404


async def test_a_room_that_is_still_running_keeps_its_grounding(
    db, ingestion, storage, sessions, funded_account
):
    """422 while the room is live, because the alternative is a silent one.

    The Auditor cross-checks live speech against these claims. Deleting them
    mid-interrogation would leave the user paying metered minutes for a panel
    that has quietly stopped being able to catch anything, with nothing on screen
    saying so. A session is capped at twelve minutes, so the wait is bounded and
    the user has something to do about it.
    """
    material = await extracted(db, ingestion, storage, funded_account)
    await sessions.start(user_id=funded_account.user_id, material_ids=[material.id])

    with pytest.raises(Exception) as refused:
        await deleting(db, storage, funded_account).delete(
            material.id, user_id=funded_account.user_id
        )

    assert refused.value.code == "material_in_use"
    material_row, claims = await rows(db, material.id)
    assert material_row is not None
    assert material_row.deleted_at is None
    assert claims == 1


async def test_the_deck_goes_once_the_room_has_closed(
    db, ingestion, storage, sessions, funded_account
):
    """The refusal above is a wait, not a rule about ever deleting it.

    Worth its own test because "in use" that never clears is indistinguishable
    from a material that cannot be deleted at all — and a settled session still
    holds its `session_materials` rows.
    """
    material = await extracted(db, ingestion, storage, funded_account)
    session = await sessions.start(
        user_id=funded_account.user_id, material_ids=[material.id]
    )
    await sessions.activate(session_id=session.id)
    await sessions.begin_finalizing(
        session_id=session.id, end_reason=EndReason.USER_ENDED
    )
    await sessions.settle(session_id=session.id)

    await deleting(db, storage, funded_account).delete(
        material.id, user_id=funded_account.user_id
    )

    await db.refresh(material)
    assert material.deleted_at is not None


async def test_a_deck_deleted_while_it_is_being_read_leaves_nothing_behind(
    db, ingestion, storage, account
):
    """The window the design actually had to choose a shape for.

    "I uploaded the wrong deck" is not a rare deletion, it is the most likely
    one — and it lands squarely while the sweep is reading the file. The worker
    checks whether the material survived before it writes a thumbnail or pays a
    model: without the check it would render an object into a bucket the user has
    just been told is empty, with nothing left pointing at it to ever clean up.
    """
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(MARGIN))

    class DeletesMidRead:
        """The DELETE arriving while the worker has the file open."""

        def __init__(self, wrapped) -> None:
            self._wrapped = wrapped

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

        async def get(self, key: str):
            data = await self._wrapped.get(key)
            await deleting(db, storage, account).delete(
                material.id, user_id=account.user_id
            )
            return data

    await extraction(db, DeletesMidRead(storage), model).sweep()

    assert model.calls == []
    material_row, claims = await rows(db, material.id)
    assert material_row is None
    assert claims == 0
    assert await storage.get(material.storage_key) is None


async def test_a_worker_holding_the_deck_still_records_what_it_spent(
    db, ingestion, storage, account
):
    """The purge waits for the worker rather than deleting out from under it.

    A material being read is skipped until the extraction that holds it ends. The
    alternative loses the cost row for a model call that has already been paid
    for — and unrecorded spend on a deleted deck is exactly the shape of the
    abuse `extraction_costs` exists to make visible.
    """
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    await claim(ingestion)

    await deleting(db, storage, account).delete(material.id, user_id=account.user_id)
    await extraction(db, storage, FakeExtractionModel()).sweep()

    await db.refresh(material)
    assert material.state is MaterialState.EXTRACTING

    await ingestion.settle_extraction(material.id, result=reading(MARGIN))
    await extraction(db, storage, FakeExtractionModel()).sweep()

    assert (await rows(db, material.id))[0] is None
    spend = await db.scalars(
        select(ExtractionCost).where(ExtractionCost.material_id == material.id)
    )
    assert len(list(spend)) == 1


async def test_the_cost_of_a_deleted_deck_is_still_on_the_books(
    db, ingestion, storage, account
):
    """No foreign key, on purpose (`docs/ingestion.md`).

    Extraction is unmetered cost with no revenue attached, so "upload, extract,
    delete, repeat" is the abuse the table exists to catch — and a cascading
    delete would let it erase its own trail one deck at a time.
    """
    material = await extracted(db, ingestion, storage, account)

    await deleting(db, storage, account).delete(material.id, user_id=account.user_id)
    await extraction(db, storage, FakeExtractionModel()).sweep()

    spend = await db.scalars(
        select(ExtractionCost).where(ExtractionCost.material_id == material.id)
    )
    assert [row.pages for row in spend] == [1]


async def test_a_deleted_deck_cannot_ground_the_next_room(
    db, ingestion, storage, sessions, funded_account
):
    """Deleted is invisible from the moment of the request, not from the purge.

    Between the mark and the sweep the row is still in the table. A session
    started in that window would attach material the user has been told is gone,
    and the panel would attack a deck that no longer exists.
    """
    material = await extracted(db, ingestion, storage, funded_account)
    await deleting(db, storage, funded_account).delete(
        material.id, user_id=funded_account.user_id
    )

    with pytest.raises(Exception) as refused:
        await sessions.start(
            user_id=funded_account.user_id, material_ids=[material.id]
        )

    assert refused.value.code == "material_not_found"


async def test_a_delete_the_bucket_refuses_is_tried_again(
    db, ingestion, storage, account
):
    """One bad afternoon at the store must not end with the object still there.

    Same reasoning as the source purge: removing an object cannot join the
    transaction that marks the row, so the mark is the durable promise and the
    retry is what makes it true. The row stays until the object is actually gone
    — it is the only thing still pointing at the key.
    """
    material = await extracted(db, ingestion, storage, account)
    thumbnail_key = material.thumbnail_key

    broken = RefusesToDelete(storage, failures=10)
    await deleting(db, broken, account).delete(material.id, user_id=account.user_id)
    await extraction(db, broken, FakeExtractionModel()).sweep()

    assert (await rows(db, material.id))[0] is not None
    assert await storage.get(thumbnail_key) is not None

    await extraction(db, storage, FakeExtractionModel()).sweep()

    assert (await rows(db, material.id))[0] is None
    assert await storage.get(thumbnail_key) is None


async def test_deleting_somebody_elses_deck_is_a_404(
    client, db, ingestion, storage, account, bearer
):
    """Not found rather than forbidden, and the material is untouched.

    A 403 confirms the id names a real material, which is the only thing an
    attacker walking ids is trying to learn.
    """
    stranger = Account(user_id=uuid.uuid4(), entitlement_tier="free")
    db.add(stranger)
    await db.commit()
    material = await extracted(db, ingestion, storage, account)

    refused = await client.delete(
        f"/v1/materials/{material.id}", headers=bearer(stranger.user_id)
    )

    assert refused.status_code == 404
    await db.refresh(material)
    assert material.deleted_at is None


async def test_an_unauthenticated_caller_deletes_nothing(client):
    """401 from the dependency, before any handler runs."""
    deleted = await client.delete(f"/v1/materials/{uuid.uuid4()}")

    assert deleted.status_code == 401


async def test_the_deletion_is_provable_afterwards(db, ingestion, storage, account):
    """An `audit_events` row, which is the only thing that outlives the material.

    This is the App Store answer with a date on it: the retention promise is
    unfalsifiable without a record that the user asked and we acted. It carries
    no foreign key for the same reason the rest of the table does not — the row
    has to survive the thing it describes, which here is the entire point.
    """
    material = await extracted(db, ingestion, storage, account)

    await deleting(db, storage, account).delete(material.id, user_id=account.user_id)

    events = await db.scalars(
        select(AuditEvent).where(
            AuditEvent.event_type == AuditEventType.MATERIAL_DELETED.value
        )
    )
    event = list(events)
    assert len(event) == 1
    assert event[0].user_id == account.user_id
    assert event[0].actor == "user"
    assert event[0].context["material_id"] == str(material.id)
