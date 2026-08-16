"""The upload handshake, over HTTP.

Three calls, and the phone is the one that does the middle one: ask for a URL,
PUT the bytes straight to storage, say it landed. What these tests add on top of
`test_ingestion.py` is what the transport introduces — who is calling, whether
they own what they are touching, and what a refusal looks like on the wire.

The PUT goes to a real MinIO rather than to the app, which is the point: CLAUDE.md
requires uploaded material be delivered by presigned URL and *never proxied*, so
the bytes must not pass through a route here at all.
"""

from __future__ import annotations

import io
import uuid

import httpx
import pytest
from PIL import Image

from app.modules.auth.tokens import AccessTokens
from app.modules.billing.models import Account
from app.modules.ingestion.schemas import MaterialState

from tests.conftest import SECRET
from tests.materials import FakeExtractionModel, extracted, extraction, reading, uploaded
from tests.pdfs import minimal_pdf

PDF = "application/pdf"
DECK = b"%PDF-1.7 a deck, for the purposes of this test"


@pytest.fixture
def bearer():
    """Headers that authenticate as a given user."""

    def headers(user_id: uuid.UUID) -> dict[str, str]:
        token = AccessTokens(secret=SECRET).issue(user_id=user_id)
        return {"Authorization": f"Bearer {token}"}

    return headers


def declaration(byte_size: int = len(DECK), content_type: str = PDF) -> dict:
    return {
        "filename": "q3-board-deck.pdf",
        "content_type": content_type,
        "byte_size": byte_size,
    }


async def test_the_whole_handshake_lands_a_deck_in_the_extraction_queue(
    client, account, bearer
):
    """The tracer bullet: register, PUT to storage, complete.

    The middle step deliberately does not touch this application. A material
    that arrived through an API route would be material we proxied, and the size
    of a deck is the reason that rule exists — a 100MB upload occupying a worker
    is a worker not answering anything else.
    """
    headers = bearer(account.user_id)

    registered = await client.post("/v1/materials", json=declaration(), headers=headers)
    assert registered.status_code == 201, registered.text
    body = registered.json()
    assert body["state"] == MaterialState.AWAITING_UPLOAD.value

    async with httpx.AsyncClient() as direct:
        stored = await direct.put(
            body["upload_url"], content=DECK, headers={"Content-Type": PDF}
        )
    assert stored.status_code == 200, stored.text

    completed = await client.post(
        f"/v1/materials/{body['id']}/complete", headers=headers
    )

    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == MaterialState.PENDING.value


async def test_a_response_never_carries_the_storage_key(client, account, bearer):
    """Minimum necessary fields (CLAUDE.md).

    The key is an internal locator, and the only sanctioned way to reach an
    object is a presigned URL issued after an ownership check. Publishing the
    key invites a client that builds its own — and the key contains another
    user's id one substitution away.
    """
    registered = await client.post(
        "/v1/materials", json=declaration(), headers=bearer(account.user_id)
    )

    # Asserted before the absence, because "no such field" is also what a 404
    # body says. Without this line the test passes against an application that
    # has no such endpoint at all, which is how it behaved when first written.
    assert registered.status_code == 201, registered.text
    assert "storage_key" not in registered.json()


async def test_an_oversized_file_is_refused_with_the_tier_that_would_take_it(
    client, account, bearer
):
    """413 on the wire, carrying copy the app can show verbatim.

    The one legitimate paywall in ingestion, and it is pre-session: a published
    limit the user chose their plan against, refused before any byte moves.
    """
    refused = await client.post(
        "/v1/materials",
        json=declaration(byte_size=12 * 1024 * 1024),
        headers=bearer(account.user_id),
    )

    assert refused.status_code == 413
    error = refused.json()["error"]
    assert error["code"] == "material_too_large"
    assert "Starter accepts up to 25 MB." in error["message"]


async def test_an_unreadable_type_is_refused_with_no_upgrade_offered(
    client, account, bearer
):
    """415, and nothing to sell — no tier accepts an executable."""
    refused = await client.post(
        "/v1/materials",
        json=declaration(content_type="application/x-msdownload"),
        headers=bearer(account.user_id),
    )

    assert refused.status_code == 415
    assert refused.json()["error"]["code"] == "unsupported_material_type"


async def test_a_negative_size_never_reaches_the_signer(client, account, bearer):
    """422 from the schema, before anything is signed.

    A signed `Content-Length` is arithmetic somebody else performs, and handing
    a store a negative one is the kind of input that produces a vendor-specific
    error rather than a refusal. Pydantic answers it here instead.
    """
    refused = await client.post(
        "/v1/materials", json=declaration(byte_size=-1), headers=bearer(account.user_id)
    )

    assert refused.status_code == 422


async def test_the_limits_endpoint_describes_the_caller_and_the_rung_above(
    client, account, bearer
):
    """What lets the app refuse locally, with no round trip and no partial upload.

    The server refusal stays the real wall. This exists so the tier table has
    one home — the alternative is the app holding its own copy, where a pricing
    change ships as an app release and the two disagree silently.
    """
    limits = await client.get("/v1/materials/limits", headers=bearer(account.user_id))

    assert limits.status_code == 200
    body = limits.json()
    assert body["tier"] == "free"
    assert body["max_upload_bytes"] == 10 * 1024 * 1024
    assert PDF in body["accepted_content_types"]
    assert body["upgrade"]["tier"] == "starter"
    assert body["upgrade"]["max_upload_bytes"] == 25 * 1024 * 1024


async def test_the_top_tier_is_offered_no_upgrade(client, db, bearer):
    """Nothing above pro, so no prompt — and no `KeyError` producing a 500."""
    account = Account(user_id=uuid.uuid4(), entitlement_tier="pro")
    db.add(account)
    await db.commit()

    limits = await client.get("/v1/materials/limits", headers=bearer(account.user_id))

    assert limits.json()["upgrade"] is None


async def test_limits_is_a_route_and_not_a_material_id(client, account, bearer):
    """A guard against a routing accident, not against a user.

    `/materials/limits` and `/materials/{material_id}` share a shape, and the
    one declared second never matches. Getting the order wrong turns the limits
    endpoint into a malformed-UUID error, which is a 422 nobody would think to
    look for in a route ordering.
    """
    assert (
        await client.get("/v1/materials/limits", headers=bearer(account.user_id))
    ).status_code == 200


async def test_an_unauthenticated_caller_gets_nothing(client):
    """401 before any handler runs — the dependency, not a check inside one."""
    for call in (
        client.post("/v1/materials", json=declaration()),
        client.get("/v1/materials/limits"),
        client.get(f"/v1/materials/{uuid.uuid4()}"),
    ):
        assert (await call).status_code == 401


async def test_another_account_is_told_the_material_does_not_exist(
    client, account, db, bearer
):
    """404 rather than 403, for the reason sessions gives.

    A 403 confirms the id names a real material, which is the only thing an
    attacker walking ids is trying to learn — and the caller's next move is
    identical either way.
    """
    stranger = Account(user_id=uuid.uuid4(), entitlement_tier="free")
    db.add(stranger)
    await db.commit()

    registered = await client.post(
        "/v1/materials", json=declaration(), headers=bearer(account.user_id)
    )
    material_id = registered.json()["id"]

    for response in (
        await client.get(
            f"/v1/materials/{material_id}", headers=bearer(stranger.user_id)
        ),
        await client.post(
            f"/v1/materials/{material_id}/complete",
            headers=bearer(stranger.user_id),
        ),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "material_not_found"


async def test_completing_an_upload_that_never_happened_is_refused(
    client, account, bearer
):
    """422, while the user is still on the screen that can do something about it.

    Without it the row enters the extraction queue pointing at nothing: the
    sweep claims it, pays to open an object that is not there, fails, requeues.
    """
    headers = bearer(account.user_id)
    registered = await client.post("/v1/materials", json=declaration(), headers=headers)

    refused = await client.post(
        f"/v1/materials/{registered.json()['id']}/complete", headers=headers
    )

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "material_not_uploaded"


async def test_reading_a_material_back_does_not_hand_out_another_upload_url(
    client, account, bearer
):
    """The URL is a bearer credential for one object, issued once, on purpose.

    A GET that re-signed would turn every read into a fresh write capability
    against a material that may already hold an extracted deck.
    """
    headers = bearer(account.user_id)
    registered = await client.post("/v1/materials", json=declaration(), headers=headers)

    read = await client.get(f"/v1/materials/{registered.json()['id']}", headers=headers)

    assert read.status_code == 200
    assert "upload_url" not in read.json()


async def test_a_read_hands_back_a_url_the_thumbnail_actually_comes_down(
    client, db, ingestion, storage, account, bearer
):
    """The other half of the retention promise, and the half a user can see.

    `test_retention.py` proves the thumbnail is kept when the deck is destroyed.
    Kept and unreachable is the same as not kept: the material list would show a
    grey rectangle for a document whose only surviving likeness is sitting in the
    bucket. The URL is fetched here rather than merely asserted non-null, because
    a plausible-looking signed URL that 403s looks identical from the row.
    """
    material = await extracted(db, ingestion, storage, account)

    read = await client.get(
        f"/v1/materials/{material.id}", headers=bearer(account.user_id)
    )

    assert read.status_code == 200, read.text
    url = read.json()["thumbnail_url"]
    assert url is not None

    async with httpx.AsyncClient() as direct:
        fetched = await direct.get(url)
    assert fetched.status_code == 200, fetched.text
    assert Image.open(io.BytesIO(fetched.content)).format == "JPEG"


async def test_a_material_with_no_thumbnail_yet_says_so(client, account, bearer):
    """Null rather than a URL that will 404 once somebody clicks it.

    Every material spends its first minutes here — registered, uploaded, waiting
    its turn in the queue — and a client cannot tell a slow render from a broken
    one if the field is populated either way.
    """
    headers = bearer(account.user_id)
    registered = await client.post("/v1/materials", json=declaration(), headers=headers)

    read = await client.get(f"/v1/materials/{registered.json()['id']}", headers=headers)

    assert read.json()["thumbnail_url"] is None


async def test_a_deck_that_could_not_be_read_still_shows_what_it_was(
    client, db, ingestion, storage, account, bearer
):
    """The one state where recognising the document matters most.

    A failed material is terminal and the answer is "upload it again" — which
    requires the user to know *which* of the four files on the screen to find
    again. `filename` alone is `deck-final-v3.pdf`, twice.
    """
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(complete=False, retryable=False))
    await extraction(db, storage, model).sweep()

    read = await client.get(
        f"/v1/materials/{material.id}", headers=bearer(account.user_id)
    )

    body = read.json()
    assert body["state"] == MaterialState.FAILED.value
    assert body["thumbnail_url"] is not None


async def test_the_signed_url_reaches_the_thumbnail_and_not_the_deck(
    client, db, ingestion, storage, account, bearer
):
    """A read capability for twenty kilobytes of downscaled first page.

    The source document is deleted by the time this is issued, so today the
    distinction is theoretical — but the URL is a bearer credential scoped to
    exactly one key, and the key it is scoped to must never become the one the
    user's confidential financials are under.
    """
    material = await extracted(db, ingestion, storage, account)

    read = await client.get(
        f"/v1/materials/{material.id}", headers=bearer(account.user_id)
    )

    url = read.json()["thumbnail_url"]
    assert material.thumbnail_key in url
    assert material.storage_key not in url
