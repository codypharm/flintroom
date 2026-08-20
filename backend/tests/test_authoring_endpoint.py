"""The routes behind the panelist form.

Thin by `CLAUDE.md`, so what is asserted here is the *edge*: who may call,
what a refusal looks like, and that a user's own words come back out. The rules
about editing and retiring belong to `test_authoring_service.py`, which is where
they are enforced.
"""

from __future__ import annotations

import uuid

import pytest

from app.agents.authored import CUSTOM_PREFIX
from app.modules.billing.models import Account

pytestmark = pytest.mark.asyncio

A_DRAFT = {
    "title": "The Board Chair",
    "persona": "Unimpressed by anything that is not a number.",
    "domains": ["margin", "runway"],
    "voice": None,
}


@pytest.fixture
async def pro(db) -> Account:
    account = Account(user_id=uuid.uuid4(), entitlement_tier="pro")
    db.add(account)
    await db.commit()
    return account


async def test_writing_one_needs_an_account(client):
    written = await client.post("/v1/archetypes/mine", json=A_DRAFT)

    assert written.status_code == 401


async def test_a_free_account_is_told_what_the_plan_does_not_include(
    client, bearer, account
):
    """403 and a code the client can branch on, never a silent empty list.

    §4.5 keeps the upsell out of the way of a rehearsal, so this says what is
    true and lets the client decide whether to mention the plan.
    """
    written = await client.post(
        "/v1/archetypes/mine", json=A_DRAFT, headers=bearer(account.user_id)
    )

    assert written.status_code == 403
    assert written.json()["error"]["code"] == "insufficient_entitlement"


async def test_a_pro_account_writes_one_and_gets_it_back(client, bearer, pro):
    written = await client.post(
        "/v1/archetypes/mine", json=A_DRAFT, headers=bearer(pro.user_id)
    )

    assert written.status_code == 201
    body = written.json()
    assert body["name"].startswith(CUSTOM_PREFIX)
    assert body["title"] == "The Board Chair"
    assert body["persona"] == A_DRAFT["persona"]


async def test_their_own_words_come_back_and_ours_do_not(client, bearer, pro):
    """The persona returns; the attack strategy we composed does not.

    A shipped archetype never publishes its prompt text, and the reason carries:
    *"a picker that prints the attack strategy is a rehearsal the user has
    already had."* Theirs is theirs — but what we wrote around it stays ours.
    """
    written = await client.post(
        "/v1/archetypes/mine", json=A_DRAFT, headers=bearer(pro.user_id)
    )

    assert "attack_strategy" not in written.json()
    assert "Never accept a number" not in written.text


async def test_a_domain_we_do_not_route_on_is_refused(client, bearer, pro):
    """422, not a silent drop. A panelist seated with an unknown domain would
    never be the one an interruption reaches, and its author would have no way
    to find out why.
    """
    written = await client.post(
        "/v1/archetypes/mine",
        json={**A_DRAFT, "domains": ["vibes"]},
        headers=bearer(pro.user_id),
    )

    assert written.status_code == 422


async def test_a_panelist_with_no_domain_is_refused(client, bearer, pro):
    written = await client.post(
        "/v1/archetypes/mine",
        json={**A_DRAFT, "domains": []},
        headers=bearer(pro.user_id),
    )

    assert written.status_code == 422


async def test_a_voice_we_do_not_cast_is_refused(client, bearer, pro):
    written = await client.post(
        "/v1/archetypes/mine",
        json={**A_DRAFT, "voice": "gravelly"},
        headers=bearer(pro.user_id),
    )

    assert written.status_code == 422


async def test_a_persona_longer_than_the_cap_is_refused(client, bearer, pro):
    """The cap is fencing rather than storage — §2. A page is room to argue with
    the instructions underneath it; a paragraph describes somebody.
    """
    written = await client.post(
        "/v1/archetypes/mine",
        json={**A_DRAFT, "persona": "x" * 401},
        headers=bearer(pro.user_id),
    )

    assert written.status_code == 422


async def test_the_roster_comes_back_empty_rather_than_missing(client, bearer, pro):
    """An account that has written none has an empty panel, not an error."""
    roster = await client.get("/v1/archetypes/mine", headers=bearer(pro.user_id))

    assert roster.status_code == 200
    assert roster.json() == []


async def test_a_second_panelist_with_one_title_is_refused_in_words(
    client, bearer, pro
):
    await client.post("/v1/archetypes/mine", json=A_DRAFT, headers=bearer(pro.user_id))

    again = await client.post(
        "/v1/archetypes/mine", json=A_DRAFT, headers=bearer(pro.user_id)
    )

    assert again.status_code == 422
    assert again.json()["error"]["code"] == "title_already_used"


async def test_retiring_one_answers_no_content(client, bearer, pro):
    written = await client.post(
        "/v1/archetypes/mine", json=A_DRAFT, headers=bearer(pro.user_id)
    )
    name = written.json()["name"]

    gone = await client.delete(
        f"/v1/archetypes/mine/{name}", headers=bearer(pro.user_id)
    )

    assert gone.status_code == 204
    roster = await client.get("/v1/archetypes/mine", headers=bearer(pro.user_id))
    assert roster.json() == []


async def test_retiring_somebody_elses_is_not_found(client, bearer, pro, db):
    """404 rather than 403 — 403 would confirm the row exists."""
    other = Account(user_id=uuid.uuid4(), entitlement_tier="pro")
    db.add(other)
    await db.commit()
    written = await client.post(
        "/v1/archetypes/mine", json=A_DRAFT, headers=bearer(pro.user_id)
    )

    gone = await client.delete(
        f"/v1/archetypes/mine/{written.json()['name']}",
        headers=bearer(other.user_id),
    )

    assert gone.status_code == 404


async def test_editing_one_returns_what_was_stored(client, bearer, pro):
    written = await client.post(
        "/v1/archetypes/mine", json=A_DRAFT, headers=bearer(pro.user_id)
    )

    edited = await client.put(
        f"/v1/archetypes/mine/{written.json()['name']}",
        json={**A_DRAFT, "title": "The Chair"},
        headers=bearer(pro.user_id),
    )

    assert edited.status_code == 200
    assert edited.json()["title"] == "The Chair"
