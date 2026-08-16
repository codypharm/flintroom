"""Material lifecycle — the row a deck gets before it becomes claims.

The state machine is specified in `docs/ingestion.md`. What these tests hold
down is the part that fails quietly: which rows the extraction sweep is allowed
to pick up. A material nobody uploaded and a material whose extraction stalled
are both "not ready", and charging the second one twice is a second invoice.
"""

import uuid

import httpx
import pytest

from sqlalchemy.exc import IntegrityError

from app.core.errors import (
    InvalidMaterialState,
    MaterialNotFound,
    MaterialNotUploaded,
    MaterialTooLarge,
    UnsupportedMaterialType,
)
from app.modules.ingestion.models import Material
from app.modules.ingestion.schemas import MaterialState

PDF = "application/pdf"
DECK = b"%PDF-1.7 a deck, for the purposes of this test"


async def upload(url: str, body: bytes, content_type: str = PDF) -> None:
    """Do what the phone would do with the URL it was handed."""
    async with httpx.AsyncClient() as http:
        response = await http.put(
            url, content=body, headers={"Content-Type": content_type}
        )
    assert response.status_code == 200, response.text


async def test_registered_material_waits_for_its_bytes(ingestion, account):
    """Registration precedes upload, because the presign is signed against a key.

    So the row exists before the object does, and it must not be extractable in
    that window — `awaiting_upload` is what says so.
    """
    registered = await ingestion.register(
        user_id=account.user_id,
        filename="q3-board-deck.pdf",
        content_type=PDF,
        byte_size=len(DECK),
    )

    assert registered.material.state is MaterialState.AWAITING_UPLOAD
    assert registered.material.storage_key
    assert registered.upload_url


async def test_the_url_handed_out_only_accepts_the_file_that_was_declared(
    ingestion, account
):
    """The tier cap is enforced by the signature, so the declaration is binding.

    Registering a small file and then uploading a large one through the URL is
    the obvious way around a per-tier byte limit, and it is the one this proves
    closed. Asserted through the service rather than in `test_storage.py`
    because the question here is whether the service passes the declared size
    down — signing the wrong number is exactly as broken as not signing one.
    """
    registered = await ingestion.register(
        user_id=account.user_id,
        filename="q3-board-deck.pdf",
        content_type=PDF,
        byte_size=len(DECK),
    )

    async with httpx.AsyncClient() as http:
        refused = await http.put(
            registered.upload_url,
            content=DECK * 100,
            headers={"Content-Type": PDF},
        )

    assert refused.status_code == 403, refused.text


async def test_an_oversized_file_is_refused_before_a_url_is_issued(
    ingestion, account
):
    """413 before the presign, so a refusal costs the user no upload.

    This is the one legitimate paywall in ingestion: a pre-session refusal on a
    published limit the user chose their plan against. It names the cheapest
    tier that would take the file, and it does not exist as a row — nothing is
    registered, so a rejected attempt leaves nothing behind to reap.
    """
    with pytest.raises(MaterialTooLarge) as refused:
        await ingestion.register(
            user_id=account.user_id,
            filename="q3-board-deck.pdf",
            content_type=PDF,
            byte_size=12 * 1024 * 1024,
        )

    assert refused.value.status_code == 413
    assert refused.value.message == (
        "That file is 12 MB. Your plan accepts up to 10 MB. "
        "Starter accepts up to 25 MB."
    )


async def test_a_size_just_over_the_cap_does_not_read_as_equal_to_it(
    ingestion, account
):
    """Rounding is what stops the refusal contradicting itself.

    A file one byte over 10MB rounds to *"That file is 10 MB. Your plan accepts
    up to 10 MB"* — a message that reads as a bug, and earns a support ticket
    where it should have earned an upgrade. The file rounds up and the cap does
    not, so the two numbers can never collide.
    """
    with pytest.raises(MaterialTooLarge) as refused:
        await ingestion.register(
            user_id=account.user_id,
            filename="q3-board-deck.pdf",
            content_type=PDF,
            byte_size=10 * 1024 * 1024 + 1,
        )

    assert refused.value.message.startswith("That file is 10.1 MB. ")


async def test_a_file_no_tier_accepts_is_refused_without_an_upsell(
    ingestion, account
):
    """Nothing on sale would take this file, so the refusal offers nothing.

    The failure this guards is a paywall that charges for a plan which still
    refuses the upload — money taken for a problem left unsolved.
    """
    with pytest.raises(MaterialTooLarge) as refused:
        await ingestion.register(
            user_id=account.user_id,
            filename="the-entire-data-room.pdf",
            content_type=PDF,
            byte_size=4096 * 1024 * 1024,
        )

    assert "Starter" not in refused.value.message
    assert "Pro" not in refused.value.message
    assert "100 MB" in refused.value.message


async def test_a_type_we_cannot_parse_is_refused_before_a_url_is_issued(
    ingestion, account
):
    """415, and not a paywall — no tier accepts an executable.

    Kept distinct from the size refusal on purpose. Both happen before the
    presign, but only one of them has anything to sell, and a wrong-type message
    offering an upgrade would be the drift `docs/ingestion.md` warns about.
    """
    with pytest.raises(UnsupportedMaterialType) as refused:
        await ingestion.register(
            user_id=account.user_id,
            filename="deck.exe",
            content_type="application/x-msdownload",
            byte_size=1024,
        )

    assert refused.value.status_code == 415


async def test_completed_upload_becomes_extractable(ingestion, account):
    """`pending` is the one state the extraction sweep claims.

    So this transition is the moment a material starts costing money, and it is
    driven by the client saying the bytes landed rather than by registration.
    """
    registered = await ingestion.register(
        user_id=account.user_id,
        filename="q3-board-deck.pdf",
        content_type=PDF,
        byte_size=len(DECK),
    )
    await upload(registered.upload_url, DECK)

    uploaded = await ingestion.mark_uploaded(
        registered.material.id, user_id=account.user_id
    )

    assert uploaded.state is MaterialState.PENDING


async def test_a_completion_with_no_object_behind_it_is_refused(ingestion, account):
    """The client saying "uploaded" is a claim, and it is checked.

    Without the check, a client that never uploaded — or whose PUT failed while
    its retry logic reported success — puts a row into the extraction queue
    pointing at nothing. The sweep then claims it, pays a model call to open an
    object that does not exist, fails, and requeues. One HEAD makes that a
    refusal at the handshake instead, while the user is still on the screen that
    can do something about it.
    """
    registered = await ingestion.register(
        user_id=account.user_id,
        filename="q3-board-deck.pdf",
        content_type=PDF,
        byte_size=len(DECK),
    )

    with pytest.raises(MaterialNotUploaded):
        await ingestion.mark_uploaded(
            registered.material.id, user_id=account.user_id
        )

    assert registered.material.state is MaterialState.AWAITING_UPLOAD


async def test_another_account_cannot_touch_someone_elses_material(
    ingestion, account
):
    """And is told nothing that distinguishes "not yours" from "no such thing".

    A different answer for each is an enumeration oracle: a prober walks ids and
    learns which decks exist on the platform, without ever reading one.
    """
    registered = await ingestion.register(
        user_id=account.user_id,
        filename="q3-board-deck.pdf",
        content_type=PDF,
        byte_size=len(DECK),
    )
    await upload(registered.upload_url, DECK)

    with pytest.raises(MaterialNotFound):
        await ingestion.mark_uploaded(registered.material.id, user_id=uuid.uuid4())

    with pytest.raises(MaterialNotFound):
        await ingestion.mark_uploaded(uuid.uuid4(), user_id=account.user_id)


async def test_an_upload_cannot_be_completed_twice(ingestion, account):
    """Idempotency at the state machine, not at the router.

    A phone on a bad connection retries, and the second call must not put an
    already-extracting or already-`ready` material back into the sweep's queue.
    Doing so re-extracts a deck that was already paid for — the duplicate that
    `docs/ingestion.md` says is a second invoice rather than a refused write.
    """
    registered = await ingestion.register(
        user_id=account.user_id,
        filename="q3-board-deck.pdf",
        content_type=PDF,
        byte_size=len(DECK),
    )
    await upload(registered.upload_url, DECK)
    await ingestion.mark_uploaded(registered.material.id, user_id=account.user_id)

    with pytest.raises(InvalidMaterialState):
        await ingestion.mark_uploaded(registered.material.id, user_id=account.user_id)


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
        content_type=PDF,
        byte_size=len(DECK),
        storage_key=f"material/{account.user_id}/{uuid.uuid4()}",
        claimed_at=None,
    )
    db.add(material)

    with pytest.raises(IntegrityError):
        await db.commit()
