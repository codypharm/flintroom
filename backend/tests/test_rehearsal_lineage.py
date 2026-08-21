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


async def settled(sessions, settlement, db, account, *, repeats=None, name=None):
    """One finished room, so the next may start.

    Through the service rather than the endpoint: a user holds one room at a
    time, and these tests are about the lineage rather than about the lifecycle
    that already has its own suite.
    """
    session = await sessions.start(
        user_id=account.user_id, repeats=repeats, rehearsal_name=name
    )
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


# --- What the rehearsal is called -------------------------------------------
#
# A group that reads "started 11 August, three rooms" is honest and nearly
# useless. "Am I getting better at my Q3 board readout" needs the words *Q3
# board readout*, and nothing in the product captured them.
#
# The name belongs to the **lineage**, not to the room, and it is stored on
# whichever rooms were given one: the newest name in a group is the group's.
# That is what keeps a rename possible — somebody who ran three rooms before
# thinking to name the thing can name it on the fourth, and all four are it.

NAME = "Q3 board readout"


async def test_a_room_may_be_told_what_it_is_rehearsing(
    client, bearer, funded_account
):
    """The tracer. Optional, and it comes back on the room it was given to."""
    response = await client.post(
        "/v1/sessions",
        headers=bearer(funded_account.user_id),
        json={"archetypes": ["cfo"], "material_ids": [], "rehearsal_name": NAME},
    )

    assert response.status_code == 201
    assert response.json()["rehearsal_name"] == NAME


async def test_a_rerun_inherits_the_name_without_being_told_it(
    client, db, bearer, sessions, settlement, funded_account
):
    """The name is the lineage's, so a re-run does not have to carry it.

    "Run it again" is one tap. Requiring the client to send back a name it was
    given is a round trip that exists only to let the client get it wrong.
    """
    first = await settled(sessions, settlement, db, funded_account, name=NAME)

    again = await settled(sessions, settlement, db, funded_account, repeats=first.id)

    rooms = (
        await client.get("/v1/sessions", headers=bearer(funded_account.user_id))
    ).json()

    assert {room["id"]: room["rehearsal_name"] for room in rooms} == {
        str(first.id): NAME,
        str(again.id): NAME,
    }


async def test_the_newest_name_is_the_rehearsals_name(
    client, db, bearer, sessions, settlement, funded_account
):
    """Naming it late names the whole run, not only the room you typed it into.

    Almost nobody names the first room — they discover on the third attempt that
    they are working on a thing. If only the first room could hold a name, that
    presenter could never name their rehearsal at all.
    """
    first = await settled(sessions, settlement, db, funded_account)
    await settled(sessions, settlement, db, funded_account, repeats=first.id, name=NAME)

    rooms = (
        await client.get("/v1/sessions", headers=bearer(funded_account.user_id))
    ).json()

    assert {room["rehearsal_name"] for room in rooms} == {NAME}


async def test_a_name_of_only_whitespace_is_no_name(client, bearer, funded_account):
    """Stored as absent rather than as a string of spaces.

    A text field somebody tabbed through submits `" "`, and a lineage headed by
    a blank line reads as a rendering fault rather than as an unnamed room.
    """
    response = await client.post(
        "/v1/sessions",
        headers=bearer(funded_account.user_id),
        json={"archetypes": ["cfo"], "material_ids": [], "rehearsal_name": "   "},
    )

    assert response.json()["rehearsal_name"] is None


async def test_a_name_longer_than_a_heading_is_refused(
    client, bearer, funded_account
):
    """422 rather than truncation. This is a heading, not a description, and a
    field with no bound is a field somebody pastes a transcript into."""
    response = await client.post(
        "/v1/sessions",
        headers=bearer(funded_account.user_id),
        json={"archetypes": ["cfo"], "material_ids": [], "rehearsal_name": "x" * 200},
    )

    assert response.status_code == 422


# --- What a re-run reproduces ------------------------------------------------
#
# "Run it again" restores the panel and the material. It did not restore the
# **pressure**, so the button gave back a different room than the one it named:
# the rung was read from the account, and every debrief moves that — including
# debriefs of entirely unrelated arguments.
#
#     Board readout, attempt 1, runs at Relentless.
#     Demo day rehearsed badly, and the account drops to Gentle.
#     Board readout, attempt 2, runs at Gentle.
#
# Two adjacent attempts at one pitch, pressed differently for reasons nothing to
# do with that pitch. That breaks the same-rung comparison in `docs/rehearsals.md`
# decision 9 exactly where it is wanted, and it puts a rung on the Progress
# screen that the person reading it cannot explain.
#
# So a room that repeats another opens at the rung that rehearsal last ran at.
# The account's rung is untouched and keeps meaning what
# `docs/difficulty-calibration.md` decision 3 says it means — it is simply no
# longer what a *repeat* reads.

from datetime import timedelta

from sqlalchemy import update

from app.agents.difficulty import GENTLE, RELENTLESS, STANDARD
from app.modules.billing.models import Account


async def _account_at(db, account, level, *, chosen_at=None):
    """Put the account on a rung, optionally as an explicit user choice."""
    await db.execute(
        update(Account)
        .where(Account.user_id == account.user_id)
        .values(difficulty_level=level, difficulty_chosen_at=chosen_at)
    )
    await db.commit()


async def test_a_rerun_opens_at_the_rung_that_rehearsal_last_ran_at(
    db, sessions, settlement, funded_account
):
    """The tracer. The account moved; the rehearsal did not."""
    first = await settled(sessions, settlement, db, funded_account)
    await sessions.ran_at(session_id=first.id, level=RELENTLESS)
    await _account_at(db, funded_account, GENTLE)

    again = await settled(sessions, settlement, db, funded_account, repeats=first.id)

    assert await sessions.difficulty_of(session_id=again.id) == RELENTLESS


async def test_a_fresh_argument_opens_at_the_account_rung(
    db, sessions, settlement, funded_account
):
    """Nothing is repeated, so there is no rehearsal to inherit from.

    This is decision 3 still doing its job: resilience earned across arguments
    is what a new argument starts from.
    """
    await _account_at(db, funded_account, STANDARD)

    fresh = await settled(sessions, settlement, db, funded_account)

    assert await sessions.difficulty_of(session_id=fresh.id) == STANDARD


async def test_choosing_a_rung_after_the_last_attempt_beats_the_pin(
    db, sessions, settlement, funded_account
):
    """The control on the setup screen still overrides.

    Without this the pin is a trap: a rehearsal stuck at Gentle could never be
    made harder, and the one control the user has over pressure would silently
    do nothing on the screen where it matters most.
    """
    first = await settled(sessions, settlement, db, funded_account)
    await sessions.ran_at(session_id=first.id, level=GENTLE)

    again = await settled(sessions, settlement, db, funded_account, repeats=first.id)
    # Chosen after that attempt ran, which is what makes it an answer to it.
    await _account_at(db, funded_account, RELENTLESS, chosen_at=again.started_at)

    assert await sessions.difficulty_of(session_id=again.id) == RELENTLESS


async def test_a_choice_made_before_the_last_attempt_does_not_beat_the_pin(
    db, sessions, settlement, funded_account
):
    """An old preference is not an instruction about this rehearsal.

    Somebody who set Relentless months ago, then ran this rehearsal at Gentle,
    has said the more recent thing with the room they actually ran.
    """
    first = await settled(sessions, settlement, db, funded_account)
    await sessions.ran_at(session_id=first.id, level=GENTLE)

    again = await settled(sessions, settlement, db, funded_account, repeats=first.id)
    # Strictly before that attempt. A choice made at the same instant is the
    # ordinary case — tap the rung, tap Start — and that one is meant to win.
    await _account_at(
        db,
        funded_account,
        RELENTLESS,
        chosen_at=first.started_at - timedelta(days=30),
    )

    assert await sessions.difficulty_of(session_id=again.id) == GENTLE


async def test_a_rehearsal_whose_rooms_never_ran_falls_back_to_the_account(
    db, sessions, settlement, funded_account
):
    """A room started and never joined has no rung, because there was no room.

    `ran_at` is written when the room is assembled, so a lineage of rooms that
    all failed to provision has nothing to inherit and the account answers.
    """
    first = await settled(sessions, settlement, db, funded_account)
    await _account_at(db, funded_account, STANDARD)

    again = await settled(sessions, settlement, db, funded_account, repeats=first.id)

    assert await sessions.difficulty_of(session_id=again.id) == STANDARD
