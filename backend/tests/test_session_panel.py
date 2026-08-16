"""Who is in the room, decided when the room opens and never after.

The panel has existed as a pure function since Phase 3 began — `assemble` builds
one, `interrogate` runs a turn on one — and nothing has ever seated one in a
session. These tests are the wiring: a room now knows who is in it, and says so.

Fixed at start, for the same reason material is (`docs/ingestion.md`). A panel
that could change mid-interrogation is a reference set that moves under the
Auditor, and *"why did nobody challenge that"* stops having an answer.
"""

from __future__ import annotations

import pytest

from app.agents.archetypes import DEFAULT_PANEL, LIBRARY
from app.core.errors import DuplicatePanelist, PanelTooLarge
from app.modules.sessions.service import SessionService

pytestmark = pytest.mark.asyncio


async def test_a_room_seats_the_archetypes_it_was_started_with(db, funded_account):
    """The tracer bullet: names in, panel out, in the order asked.

    Order is not decoration. `routing.choose` breaks a tie on the panel's own
    index, so the seat a user gave an archetype is a real input to who speaks —
    and a room reassembled from the database in a different order is a different
    room.
    """
    session = await SessionService(db).start(
        user_id=funded_account.user_id,
        archetypes=["technical_skeptic", "champion", "cfo"],
    )

    panel = await SessionService(db).panel(session_id=session.id)

    assert [archetype.name for archetype in panel] == [
        "technical_skeptic",
        "champion",
        "cfo",
    ]


async def test_a_room_nobody_configured_gets_the_panel_we_ship(db, funded_account):
    """Starting without choosing is a first-class path, not a degraded one.

    The same call `docs/ingestion.md` made for material: a user who does not want
    to assemble a room should get the mixed default — a champion, a skeptic and a
    neutral — rather than an empty one or a refusal.
    """
    session = await SessionService(db).start(user_id=funded_account.user_id)

    panel = await SessionService(db).panel(session_id=session.id)

    assert panel == DEFAULT_PANEL


async def test_an_unseatable_panel_leaves_no_room_behind(db, funded_account):
    """A refused start must not consume the caller's one live session.

    The cheap version of this bug is invisible: the session row inserts, the
    panel check fails afterwards, and the user is told their panel is too big and
    then — on every retry, with a panel that fits — that they already have a
    session. They would be locked out until the reaper swept, roughly a minute of
    a product that is supposed to open a room in seconds.
    """
    with pytest.raises(PanelTooLarge):
        await SessionService(db).start(
            user_id=funded_account.user_id,
            archetypes=[archetype.name for archetype in LIBRARY[:4]],
        )

    assert await SessionService(db).start(user_id=funded_account.user_id) is not None


async def test_the_same_archetype_cannot_take_two_seats(db, funded_account):
    """Refused, not quietly collapsed to one.

    The two honest options are deduping and refusing, and they differ in what the
    user learns. Deduping seats a room smaller than the one they assembled and
    tells them nothing — they find out by noticing the panel is thinner than they
    chose, which reads as a broken product rather than a rejected request. It is
    the reasoning `ArchetypeNotFound` already settled for a name that does not
    exist, and a name that appears twice is the same mistake.

    Material goes the other way and deliberately: attaching the same deck twice
    is a client retrying, and there is no such thing as a room grounded in one
    deck *more*. A second CFO is a different room.
    """
    with pytest.raises(DuplicatePanelist):
        await SessionService(db).start(
            user_id=funded_account.user_id, archetypes=["cfo", "champion", "cfo"]
        )


async def test_a_client_can_assemble_a_room_and_is_told_who_is_in_it(
    client, bearer, funded_account
):
    """The wire, end to end: names up, names back.

    Echoed rather than left to the client to remember, for the same reason
    `material_ids` is: a client that reopens the app mid-session has no other way
    to find out who is in the room, and *"which panel is this"* is not a question
    the user should answer from memory.
    """
    response = await client.post(
        "/v1/sessions",
        json={"archetypes": ["champion", "cfo"]},
        headers=bearer(funded_account.user_id),
    )

    assert response.status_code == 201
    assert response.json()["archetypes"] == ["champion", "cfo"]


async def test_an_oversized_panel_is_refused_with_the_plan_that_would_seat_it(
    client, bearer, funded_account
):
    """422, and a message that names the rung above rather than dead-ending.

    The tone `MaterialTooLarge` set. A cap is the one honest moment to say what
    lifts it, and this is the moment the user is deciding what the product is
    worth to them.
    """
    response = await client.post(
        "/v1/sessions",
        json={"archetypes": [archetype.name for archetype in LIBRARY[:4]]},
        headers=bearer(funded_account.user_id),
    )

    assert response.status_code == 422
    refusal = response.json()["error"]
    assert refusal["code"] == "panel_too_large"
    assert "Starter" in refusal["message"]
