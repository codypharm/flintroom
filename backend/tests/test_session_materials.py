"""Attaching a deck to a room — the join that makes any of ingestion reachable.

Everything before this exists in its own corner: material uploads, extracts and
becomes claims, and no session has ever heard of it. `POST /v1/sessions` took no
body at all, so a session was *"open a room for the caller"* and material had
nowhere to attach even once it existed.

What these tests hold down is the refusal, not the happy path. A session that
grounds itself in a half-extracted deck is the failure `docs/ingestion.md`
refused when it made extraction asynchronous: the Auditor's reference set would
change mid-session, so the same spoken claim could pass at minute two and fail
at minute six — and *"why did the panel miss that"* becomes unanswerable.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import MaterialNotFound, MaterialNotReady
from app.modules.auth.tokens import AccessTokens
from tests.conftest import SECRET
from tests.materials import extracted, uploaded
from tests.pdfs import minimal_pdf


async def test_a_room_can_be_grounded_in_a_deck(
    db, ingestion, storage, sessions, funded_account
):
    """The tracer bullet, through the real pipeline rather than a row set by hand.

    A material set to `ready` without extracting would prove the join and hide
    the thing the join is for: the claims behind it are what the panel grounds
    on, and a session attached to a deck with none is exactly the ungrounded
    room Open Risk #2 says kills retention.
    """
    material = await extracted(db, ingestion, storage, funded_account)

    session = await sessions.start(
        user_id=funded_account.user_id, material_ids=[material.id]
    )

    assert await sessions.materials(session_id=session.id) == [material.id]


async def test_a_deck_still_extracting_cannot_ground_a_room(
    db, ingestion, sessions, funded_account
):
    """Refused rather than waited for, and the reason is grounding correctness.

    `docs/ingestion.md` refused to let slides land during a live interrogation:
    the Auditor's reference set would change mid-session, so the same spoken
    claim could pass at minute two and fail at minute six. A session that
    started against a half-read deck would reproduce exactly that, one layer up.
    """
    material = await uploaded(ingestion, funded_account, minimal_pdf("Margin 61%"))

    with pytest.raises(MaterialNotReady) as refusal:
        await sessions.start(
            user_id=funded_account.user_id, material_ids=[material.id]
        )

    assert "still being read" in refusal.value.message
    assert await can_still_open_a_room(sessions, funded_account)


async def test_a_deck_that_failed_is_told_to_be_uploaded_again(
    db, ingestion, storage, sessions, funded_account
):
    """Same refusal to the room, opposite advice to the person.

    Telling somebody to wait for a deck that will never finish is how a user
    sits watching a spinner that is not spinning.
    """
    material = await uploaded(ingestion, funded_account, minimal_pdf("Margin 61%"))
    await ingestion.claim_for_extraction(daily_page_ceiling=600)
    await ingestion.fail_extraction(material.id)

    with pytest.raises(MaterialNotReady) as refusal:
        await sessions.start(
            user_id=funded_account.user_id, material_ids=[material.id]
        )

    assert "upload it again" in refusal.value.message.lower()


async def test_a_room_cannot_be_grounded_in_somebody_elses_deck(
    db, ingestion, storage, sessions, funded_account, account
):
    """Not-yours and not-found are the same answer, as everywhere else here.

    Distinguishing them tells a prober which material ids exist — and this is
    the one endpoint where a leaked id would be worth having, because attaching
    a deck is how its contents reach a panel.
    """
    theirs = await extracted(db, ingestion, storage, account)

    with pytest.raises(MaterialNotFound):
        await sessions.start(
            user_id=funded_account.user_id, material_ids=[theirs.id]
        )

    assert await can_still_open_a_room(sessions, funded_account)


async def test_a_material_that_does_not_exist_is_the_same_answer(
    sessions, funded_account
):
    """The other half of the pair above, so the two cannot drift apart."""
    with pytest.raises(MaterialNotFound):
        await sessions.start(
            user_id=funded_account.user_id, material_ids=[uuid.uuid4()]
        )


async def test_a_refused_deck_leaves_no_room_behind(
    db, ingestion, sessions, funded_account
):
    """The check runs before the insert, and the ordering is the whole point.

    A session created and then refused would hold the user's one-live-session
    lock until the reaper cleared it — so a mistyped material id would lock
    somebody out of rehearsing for a minute, for an attempt that never opened a
    room.
    """
    material = await uploaded(ingestion, funded_account, minimal_pdf("Margin 61%"))

    with pytest.raises(MaterialNotReady):
        await sessions.start(
            user_id=funded_account.user_id, material_ids=[material.id]
        )

    # The proof: the very next start succeeds, which it could not do if the
    # refused attempt were still holding the lock.
    assert await sessions.start(user_id=funded_account.user_id) is not None


async def test_a_room_needs_no_deck_at_all(sessions, funded_account):
    """The deckless path is first-class, not degraded.

    `docs/auditor-grounding.md` gives the panel abundant material to attack
    without a document, and a user who does not want to wait for extraction
    starts without one rather than being blocked.
    """
    session = await sessions.start(user_id=funded_account.user_id)

    assert await sessions.materials(session_id=session.id) == []


async def test_the_same_deck_named_twice_attaches_once(
    db, ingestion, storage, sessions, funded_account
):
    """A clumsy request, not an error.

    The composite primary key would turn it into an `IntegrityError` — a 500 for
    something the user plainly meant once.
    """
    material = await extracted(db, ingestion, storage, funded_account)

    session = await sessions.start(
        user_id=funded_account.user_id, material_ids=[material.id, material.id]
    )

    assert await sessions.materials(session_id=session.id) == [material.id]


async def can_still_open_a_room(sessions, account) -> bool:
    """Proof that a refused attempt left no lock behind.

    It opens one, which is the only way to ask: the one-live-session lock is
    held by a row, so the question "is the user still free" and the act of
    using that freedom are the same operation.
    """
    return await sessions.start(user_id=account.user_id) is not None


# --- Over the wire ---------------------------------------------------------


@pytest.fixture
def bearer():
    """Headers that authenticate as a given user."""

    def headers(user_id: uuid.UUID) -> dict[str, str]:
        return {"Authorization": f"Bearer {AccessTokens(secret=SECRET).issue(user_id=user_id)}"}

    return headers


async def test_starting_a_room_over_http_echoes_its_grounding(
    client, db, ingestion, storage, bearer, funded_account
):
    """The client is told what stuck, rather than trusting what it sent.

    A client that reopens the app mid-session has no other way to find out which
    deck the room is attacking, and that is not a question a user should answer
    from memory.
    """
    material = await extracted(db, ingestion, storage, funded_account)

    response = await client.post(
        "/v1/sessions",
        json={"material_ids": [str(material.id)]},
        headers=bearer(funded_account.user_id),
    )

    assert response.status_code == 201, response.text
    assert response.json()["material_ids"] == [str(material.id)]


async def test_a_room_still_starts_with_no_body_at_all(
    client, bearer, funded_account
):
    """The call that existed before this slice must keep working.

    A mobile client cannot be force-updated, so every installed version keeps
    posting no body for as long as it exists. Requiring one would turn an
    ordinary feature into a broken app for everybody who has not updated.
    """
    response = await client.post(
        "/v1/sessions", headers=bearer(funded_account.user_id)
    )

    assert response.status_code == 201, response.text
    assert response.json()["material_ids"] == []


async def test_an_unready_deck_is_refused_on_the_wire(
    client, db, ingestion, bearer, funded_account
):
    """A typed 422 with a code, not a generic failure.

    The client has to be able to tell "wait a moment" from "your file is bad"
    without reading prose, because those are different screens.
    """
    material = await uploaded(ingestion, funded_account, minimal_pdf("Margin 61%"))

    response = await client.post(
        "/v1/sessions",
        json={"material_ids": [str(material.id)]},
        headers=bearer(funded_account.user_id),
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "material_not_ready"


async def test_a_room_refuses_more_material_than_it_can_hold(
    client, bearer, funded_account
):
    """Refused by the schema, before a single id is looked up.

    The cap is a guard rather than a considered limit — the real bound is claims,
    not files — but it has to bite somewhere, and the cheapest place is the one
    that costs no queries.
    """
    response = await client.post(
        "/v1/sessions",
        json={"material_ids": [str(uuid.uuid4()) for _ in range(11)]},
        headers=bearer(funded_account.user_id),
    )

    assert response.status_code == 422, response.text
