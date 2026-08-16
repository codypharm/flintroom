"""What a client is shown before it can assemble a room.

`SessionStart.archetypes` takes names, and a name is only usable by somebody who
knows which ones exist. Without this endpoint the panel picker would have to ship
the library as a hardcoded copy inside the app, where adding an archetype means
an app release and the two lists can disagree without anyone noticing — the
failure `MaterialLimits` already refused for the tier table.
"""

from __future__ import annotations

import pytest

from app.agents.archetypes import LIBRARY
from app.modules.billing.tiers import max_panel_size

pytestmark = pytest.mark.asyncio


async def test_the_catalogue_offers_every_archetype_we_ship(client, bearer, account):
    """All of them, whatever the caller's plan seats.

    Seats limit how many go in one room, never which ones exist. A catalogue
    filtered by tier would hide the thing the upgrade buys, which is the one
    moment the upsell is honest rather than an interruption.
    """
    response = await client.get("/v1/archetypes", headers=bearer(account.user_id))

    assert response.status_code == 200
    assert [entry["name"] for entry in response.json()["archetypes"]] == [
        archetype.name for archetype in LIBRARY
    ]


async def test_the_catalogue_never_publishes_an_attack_strategy(
    client, bearer, account
):
    """Who is in the room is the user's business. What they will go after is not.

    A picker that prints *"attacks the numbers and what they assume — unit
    economics, margin at scale, the cost line nobody mentioned"* is a rehearsal
    the user has already had. The whole product is a room that gets past what
    they prepared for, and handing over the attack plan at selection time is the
    single cheapest way to make it useless.

    `persona` is withheld on a weaker but real second reason: it is prompt text,
    tuned for model behaviour, and publishing it makes every tuning change a
    user-visible copy change.
    """
    response = await client.get("/v1/archetypes", headers=bearer(account.user_id))

    body = response.text.lower()
    for archetype in LIBRARY:
        assert archetype.attack_strategy.lower() not in body
        assert archetype.persona.lower() not in body


async def test_the_catalogue_says_how_many_of_them_fit(client, bearer, account):
    """The seat count, so the app can refuse a fourth locally rather than by post.

    Same reasoning as `MaterialLimits`: the client refuses instantly with no
    round trip, and the server refusal stays the real wall.
    """
    response = await client.get("/v1/archetypes", headers=bearer(account.user_id))

    assert response.json()["seats"] == max_panel_size("free")
