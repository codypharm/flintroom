"""What a room is allowed to attack, assembled for one session.

The last hop before a panel can be grounded: seats come from `SessionService`,
claims come from ingestion, and this is where they meet as a `Grounding`. Until
it existed, `Grounding.claims` was built by hand in tests and by nothing at all
in production — an interrogation that could not cite its source, which
`CLAUDE.md` refuses to ship.
"""

from __future__ import annotations

import uuid

from app.agents.context import Said, USER
from app.modules.voice.grounding import session_grounding

from tests.materials import extracted


async def test_a_room_is_grounded_in_the_deck_attached_to_it(db, ingestion, storage, account):
    """Attached material becomes lines the panel can quote back.

    This is Open Risk #2 made concrete. Without it every challenge is a generic
    hard question, which `Product.md` §1 names as the competitor product this
    one exists to refuse — and which no amount of good voice acting rescues.
    """
    material = await extracted(db, ingestion, storage, account)

    grounding = await session_grounding(
        db, user_id=account.user_id, material_ids=[material.id]
    )

    assert grounding.claims == ("Gross margin of 61% in Q3 2026 (slide 1)",)


async def test_a_room_with_no_deck_still_opens(db, account):
    """Attaching material is optional, and an unattached room is not broken.

    `docs/auditor-grounding.md` covers both cases deliberately: without a deck
    the panel still has the user's own words to catch contradictions in. A
    grounding assembler that refused here would make material mandatory by
    accident, which is a product decision it has no business making.
    """
    grounding = await session_grounding(db, user_id=account.user_id, material_ids=[])

    assert grounding.claims == ()
    assert grounding.transcript == ()


async def test_somebody_elses_material_grounds_nothing(db, ingestion, storage, account):
    """Ownership is a predicate here, not an assumption inherited from upstream.

    The ids reaching this function come from rows already bound to a session the
    caller redeemed a ticket for, so this check should never fire. It exists
    because `CLAUDE.md` says deny by default, and because the failure it
    prevents is the worst one this module could have: another user's confidential
    deck read aloud by a panelist, in a room, as an attack.
    """
    material = await extracted(db, ingestion, storage, account)

    grounding = await session_grounding(
        db, user_id=uuid.uuid4(), material_ids=[material.id]
    )

    assert grounding.claims == ()


async def test_a_resumed_room_keeps_what_was_already_said(db, account):
    """The transcript is carried in, not rebuilt.

    Selection reads position — "who has been quiet" is a fact about order, not
    counts — so a room that reconnected mid-interrogation and started from an
    empty transcript would seat the same archetype twice and read as a panel
    with no memory.
    """
    said = (Said(speaker=USER, text="We hold 61% gross margin."),)

    grounding = await session_grounding(
        db, user_id=account.user_id, material_ids=[], transcript=said
    )

    assert grounding.transcript == said
