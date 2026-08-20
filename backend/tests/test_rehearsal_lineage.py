"""Rooms that repeat one another, grouped.

The Library already offers "Run it again", which re-seats the panel and the
material from a past room — the user saying, in as many words, *this is the
same thing again*. Until 2026-08-20 the server was never told, so five
rehearsals of one board readout were five unrelated rooms scattered through a
history ordered only by time.

Progress can then answer "am I getting better at **this**", which is a
different question from "am I getting better", and the one a rehearsal product
exists to answer. It needs no new judgement: the same per-room signals, scoped
to a group the user defined by tapping a button.

**A stable group id, not a parent pointer.** A chain of repeats would have to be
walked to be grouped, and walking it in SQL is a recursive CTE for something
that is one column. Every room in a lineage carries the same `rehearsal_id`, so
grouping is a GROUP BY.

**Null means a group of one.** No backfill: every room that already exists
becomes its own rehearsal the moment the column lands, and `COALESCE(
rehearsal_id, id)` is the group everywhere.
"""

from __future__ import annotations

from app.modules.sessions.schemas import EndReason

from tests.conftest import create_funded_account


async def settled(sessions, settlement, db, account, *, repeats=None):
    """One finished room, so the next may start.

    Through the service rather than the endpoint: a user holds one room at a
    time, and these tests are about the lineage rather than about the lifecycle
    that already has its own suite.
    """
    session = await sessions.start(user_id=account.user_id, repeats=repeats)
    await sessions.activate(session_id=session.id)
    await db.commit()
    await settlement.close(session_id=session.id, end_reason=EndReason.USER_ENDED)
    return session


async def test_a_fresh_room_is_its_own_rehearsal(client, db, bearer, funded_account):
    """Nobody said it repeats anything, so it starts a lineage of one."""
    response = await client.post(
        "/v1/sessions",
        headers=bearer(funded_account.user_id),
        json={"archetypes": ["cfo"], "material_ids": []},
    )

    assert response.status_code == 201
    assert response.json()["rehearsal_id"] == response.json()["id"]


async def test_running_a_room_again_joins_its_rehearsal(
    db, sessions, settlement, funded_account
):
    """The second room belongs to the first one's lineage."""
    first = await settled(sessions, settlement, db, funded_account)

    again = await settled(sessions, settlement, db, funded_account, repeats=first.id)

    assert again.rehearsal_id == first.id


async def test_a_chain_of_repeats_stays_one_rehearsal(
    db, sessions, settlement, funded_account
):
    """A -> B -> C is one lineage, not a chain anybody has to walk.

    The third room repeats the second, and the second's rehearsal is the first.
    Carrying the group rather than the parent is what makes this a GROUP BY
    instead of a recursive CTE.
    """
    first = await settled(sessions, settlement, db, funded_account)
    second = await settled(sessions, settlement, db, funded_account, repeats=first.id)
    third = await settled(sessions, settlement, db, funded_account, repeats=second.id)

    assert [second.rehearsal_id, third.rehearsal_id] == [first.id, first.id]


async def test_a_room_cannot_repeat_somebody_elses(
    client, db, bearer, funded_account, ledger
):
    """The lineage is a read of another row, so it is an ownership decision.

    Answered 404 rather than 403: a room somebody does not own is a room that,
    as far as they are entitled to know, is not there. Telling them it exists
    and is forbidden is the difference between a missing id and a real one.
    """
    stranger = await create_funded_account(db, ledger)
    theirs = await client.post(
        "/v1/sessions",
        headers=bearer(stranger.user_id),
        json={"archetypes": ["cfo"], "material_ids": []},
    )
    theirs_id = theirs.json()["id"]
    await client.post(
        f"/v1/sessions/{theirs_id}/end", headers=bearer(stranger.user_id)
    )

    mine = await client.post(
        "/v1/sessions",
        headers=bearer(funded_account.user_id),
        json={"archetypes": ["cfo"], "material_ids": [], "repeats": theirs_id},
    )

    assert mine.status_code == 404
