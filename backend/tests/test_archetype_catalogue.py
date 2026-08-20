"""What a client is shown before it can assemble a room.

`SessionStart.archetypes` takes names, and a name is only usable by somebody who
knows which ones exist. Without this endpoint the panel picker would have to ship
the library as a hardcoded copy inside the app, where adding an archetype means
an app release and the two lists can disagree without anyone noticing — the
failure `MaterialLimits` already refused for the tier table.
"""

from __future__ import annotations

import pytest

from sqlalchemy import select

from app.agents.archetypes import DEFAULT_PANEL, LIBRARY
from app.agents.difficulty import GENTLE, RELENTLESS
from app.agents.vocabulary import DOMAIN_TERMS
from app.agents.voices import CASTABLE
from app.modules.billing.models import Account
from app.modules.billing.tiers import max_panel_size
from app.modules.onboarding.schemas import Answers
from app.modules.onboarding.service import OnboardingService

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


async def test_the_catalogue_carries_the_rung_the_room_will_be_on(
    client, bearer, account
):
    """#55's dial, read on the request the setup screen already makes.

    Same argument the seat count is here for: it is read at the same moment, by
    the same screen, and a picker that knew the roster but not the rung would
    have to make a second round trip to render one slider. `hardest` travels
    with it so the client renders the positions the ladder actually has rather
    than a number of its own — a copy of the rung count in the app is the
    hardcoded-library failure this endpoint exists to refuse.

    A new account is on the gentle rung, from the column default.
    """
    response = await client.get("/v1/archetypes", headers=bearer(account.user_id))

    assert response.json()["difficulty"] == GENTLE
    assert response.json()["hardest"] == RELENTLESS


async def test_a_user_can_move_the_dial_themselves(client, bearer, account, db):
    """The architect's amendment: up *or* down, not only harder.

    Safe in both directions because of where the floor is. Level 1 still presses
    an unanswered question — `docs/difficulty-calibration.md` decision 4 — so
    somebody who drags this all the way down gets a gentler room and cannot turn
    the wedge off. And calibration carries on from wherever they leave it, so it
    is not a permanent opt-out either.
    """
    response = await client.put(
        "/v1/me/difficulty",
        json={"difficulty": RELENTLESS},
        headers=bearer(account.user_id),
    )

    assert response.status_code == 200
    assert response.json()["difficulty"] == RELENTLESS
    stored = await db.execute(
        select(Account.difficulty_level).where(Account.user_id == account.user_id)
    )
    assert stored.scalar_one() == RELENTLESS


async def test_a_rung_that_is_not_on_the_ladder_is_refused(client, bearer, account):
    """422, and refused rather than clamped.

    Clamping is right where a *stored* number is read back — `pressure_at` does
    it, because a live room must not end over bookkeeping. It is wrong here: this
    is a person choosing, and silently giving them level 3 when they asked for 7
    is a control that lies about what it did.
    """
    refused = await client.put(
        "/v1/me/difficulty", json={"difficulty": 7}, headers=bearer(account.user_id)
    )

    assert refused.status_code == 422


async def test_the_catalogue_says_who_is_already_in_the_chairs(
    client, bearer, account, db
):
    """The reveal, and why it cannot be a screen of its own.

    `docs/onboarding.md` promised a *"here's your room"* moment after the
    survey. It arrives here rather than at a new endpoint because the reveal and
    the setup screen are one screen in two postures (decided 2026-08-18): the
    same request already carries the roster, the seat count and the rung, and a
    second call for the three names would be a round trip for one field the
    screen needs at the same instant.

    It also makes the reveal structurally honest. These are the seats the server
    derived from the answers, not a preview the client assembled — so the room
    somebody is shown is the room `POST /v1/sessions` will build.
    """
    await OnboardingService(db).record(
        user_id=account.user_id,
        answers=Answers(role="pm", audience=["budget", "compliance"]),
    )

    body = (await client.get("/v1/archetypes", headers=bearer(account.user_id))).json()

    assert body["seated"] == ["cfo", "risk_officer", "internal_blocker"]


async def test_an_account_that_answered_nothing_still_has_a_room(
    client, bearer, account
):
    """Nobody is shown an empty table.

    Reachable by an account that predates onboarding, and by anybody who
    abandoned the survey and signed in anyway. `compose` falls through to the
    shipped default, so the screen never needs a branch for "no answers" — and
    `DEFAULT_PANEL` is the mixed room `CLAUDE.md` asks for by default.
    """
    body = (await client.get("/v1/archetypes", headers=bearer(account.user_id))).json()

    assert body["seated"] == [archetype.name for archetype in DEFAULT_PANEL]


async def test_the_catalogue_publishes_the_domains_a_panelist_may_own(
    client, bearer, account
):
    """The authoring form cannot invent this list.

    Domains are the Auditor's routing key and the server refuses one it does not
    route on, so a hardcoded copy in the app is a form that offers choices the
    API rejects — the failure this endpoint already exists to prevent for the
    archetype roster, one field along.
    """
    catalogue = await client.get("/v1/archetypes", headers=bearer(account.user_id))

    published = catalogue.json()["domains"]

    assert {one["name"] for one in published} == set(DOMAIN_TERMS)
    # Every one says what it is. `defensibility` on a chip is a column name on a
    # screen, and this audience cannot rank `proof`, `references` and
    # `resilience` against each other on sight.
    assert all(one["label"] for one in published)
    # Ordered by what is read, not by the identifier underneath it.
    assert [one["label"] for one in published] == sorted(
        one["label"] for one in published
    )


async def test_the_catalogue_publishes_the_voices_and_says_how_each_sounds(
    client, bearer, account
):
    """A picker of eight one-word keys is a picker nobody can use.

    `measured` and `smooth` are indistinguishable as labels; what separates them
    is the sentence beside each in `voices.py`, which existed only as a comment
    until a user had to choose between them.
    """
    catalogue = await client.get("/v1/archetypes", headers=bearer(account.user_id))

    published = catalogue.json()["voices"]

    assert {one["name"] for one in published} == {one.value for one in CASTABLE}
    assert all(one["sounds"] for one in published)
    # `measured` is an identifier; "Measured" is a label. A picker showing the
    # first is showing its own database.
    assert all(one["label"][0].isupper() for one in published)
