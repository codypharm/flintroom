"""Material lifecycle — the row a deck gets before it becomes claims.

The state machine is specified in `docs/ingestion.md`. What these tests hold
down is the part that fails quietly: which rows the extraction sweep is allowed
to pick up. A material nobody uploaded and a material whose extraction stalled
are both "not ready", and charging the second one twice is a second invoice.
"""

import uuid

import pytest

from sqlalchemy.exc import IntegrityError

from app.core.errors import InvalidMaterialState, MaterialNotFound
from app.modules.ingestion.models import Material
from app.modules.ingestion.schemas import MaterialState


async def test_registered_material_waits_for_its_bytes(ingestion, account):
    """Registration precedes upload, because the presign is signed against a key.

    So the row exists before the object does, and it must not be extractable in
    that window — `awaiting_upload` is what says so.
    """
    material = await ingestion.register(
        user_id=account.user_id,
        filename="q3-board-deck.pdf",
        content_type="application/pdf",
    )

    assert material.state is MaterialState.AWAITING_UPLOAD
    assert material.storage_key


async def test_completed_upload_becomes_extractable(ingestion, account):
    """`pending` is the one state the extraction sweep claims.

    So this transition is the moment a material starts costing money, and it is
    driven by the client saying the bytes landed rather than by registration.
    """
    material = await ingestion.register(
        user_id=account.user_id,
        filename="q3-board-deck.pdf",
        content_type="application/pdf",
    )

    uploaded = await ingestion.mark_uploaded(material.id, user_id=account.user_id)

    assert uploaded.state is MaterialState.PENDING


async def test_another_account_cannot_touch_someone_elses_material(
    ingestion, account
):
    """And is told nothing that distinguishes "not yours" from "no such thing".

    A different answer for each is an enumeration oracle: a prober walks ids and
    learns which decks exist on the platform, without ever reading one.
    """
    material = await ingestion.register(
        user_id=account.user_id,
        filename="q3-board-deck.pdf",
        content_type="application/pdf",
    )

    with pytest.raises(MaterialNotFound):
        await ingestion.mark_uploaded(material.id, user_id=uuid.uuid4())

    with pytest.raises(MaterialNotFound):
        await ingestion.mark_uploaded(uuid.uuid4(), user_id=account.user_id)


async def test_an_upload_cannot_be_completed_twice(ingestion, account):
    """Idempotency at the state machine, not at the router.

    A phone on a bad connection retries, and the second call must not put an
    already-extracting or already-`ready` material back into the sweep's queue.
    Doing so re-extracts a deck that was already paid for — the duplicate that
    `docs/ingestion.md` says is a second invoice rather than a refused write.
    """
    material = await ingestion.register(
        user_id=account.user_id,
        filename="q3-board-deck.pdf",
        content_type="application/pdf",
    )
    await ingestion.mark_uploaded(material.id, user_id=account.user_id)

    with pytest.raises(InvalidMaterialState):
        await ingestion.mark_uploaded(material.id, user_id=account.user_id)


async def test_the_database_refuses_a_claim_that_does_not_match_the_state(db, account):
    """`extracting` and a claim mark are the same fact, enforced below the code.

    Asserted against the database rather than through the service because that
    is where the guarantee lives: whichever sweep, migration or support script
    writes this row next, it cannot produce the two shapes that strand a
    material forever — claimed but not extracting, so the requeue never sees it;
    or extracting but unclaimed, so nothing can ever time it out.
    """
    material = Material(
        user_id=account.user_id,
        state=MaterialState.EXTRACTING,
        filename="q3-board-deck.pdf",
        content_type="application/pdf",
        storage_key=f"material/{account.user_id}/{uuid.uuid4()}",
        claimed_at=None,
    )
    db.add(material)

    with pytest.raises(IntegrityError):
        await db.commit()
