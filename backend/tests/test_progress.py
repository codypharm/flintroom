"""Whether somebody is getting better, without telling them how they spoke.

Asked for directly by the architect: *"user is meant to track their development
— how would they if they were not scored per session"*. The answer had been "no
scores", and that was over-broad. `Product.md:15` and `:392` refuse a
**delivery-metrics** scorer — *"Delivery-metrics scoring is the commodity layer
and is not the product"* — and §4.1 states the product's purpose is improvement.
A figure about whether an *argument* held is on the wedge, not against it.

**The arithmetic that would lie, and the reason it does not here.** Difficulty
escalates across sessions (#55), so a raw count of what got past somebody can
rise while they improve — same person, better answers, harder room. Every figure
below therefore travels with the rung it was earned at, and the two are never
separated on the wire.

Nothing here is new machinery. The denominator is the one
`DebriefService.weak_answers` already counts for calibration, and the fault
filter is `calibration.PRESENTER_AT_FAULT`, so a question a colleague talked
over never counts against anybody. Reusing both is the point: a second rule
about what a challenge *is* would diverge from the one that moves the ladder.
"""

from __future__ import annotations

from sqlalchemy import update

from app.agents.difficulty import RELENTLESS
from app.agents.context import USER, Said
from app.modules.sessions.models import Session as SessionModel
from app.agents.weakness import Judgement, Weakness
from app.modules.sessions.debrief import DebriefService
from app.modules.sessions.progress import ProgressService

from tests.conftest import create_funded_account
from tests.test_debrief import CountingReader, room_that_happened

ROOM = (
    Said(speaker=USER, text="We grew forty percent last quarter."),
    Said(speaker="cfo", text="Off what base, and at what cost?"),
    Said(speaker=USER, text="We are really pleased with the trajectory."),
    Said(speaker="technical_skeptic", text="What happens when volume triples?"),
    Said(speaker=USER, text="The system holds."),
)

DUCKED = Judgement(
    ordinal=1,
    quote="Off what base, and at what cost?",
    weakness=Weakness.EVASIVE,
    why="You answered with a feeling about the trend, not a base.",
)

TAKEN_AWAY = Judgement(
    ordinal=3,
    quote="What happens when volume triples?",
    weakness=Weakness.DISMISSED,
    why="Another panelist cut across before you could answer.",
)


async def debriefed(
    db, engine, sessions, settlement, account, *judged, repeats=None, name=None
):
    session = await room_that_happened(
        db, engine, sessions, settlement, account, *ROOM, repeats=repeats, name=name
    )
    await DebriefService(db, reader=CountingReader(*judged)).weak_answers(
        session_id=session.id
    )
    return session


async def test_a_room_is_counted_by_what_the_presenter_held(
    db, engine, sessions, settlement, funded_account
):
    """The tracer. Two challenges, one ducked, one held.

    The denominator is every line the panel put to them, follow-ups included —
    the same count `DebriefService` already takes for calibration, because a
    press is a second thing to handle rather than a repeat of the first.
    """
    await debriefed(db, engine, sessions, settlement, funded_account, DUCKED)

    read = await ProgressService(db).read(user_id=funded_account.user_id)

    assert len(read.rooms) == 1
    assert read.rooms[0].challenged == 2
    assert read.rooms[0].held == 1


async def test_a_question_a_colleague_took_away_is_not_held_against_them(
    db, engine, sessions, settlement, funded_account
):
    """#56, in arithmetic rather than in layout.

    `dismissed` and `not_reached` are the room's doing. Letting them count as
    failures would undo on this screen what the prep sheet says in words:
    somebody told it was not their fault, and then shown a figure that says it
    was.

    Nor is it silently counted as *held* — they never got to answer it, so it
    leaves the denominator too. The room simply put one fewer question to them.
    """
    await debriefed(
        db, engine, sessions, settlement, funded_account, DUCKED, TAKEN_AWAY
    )

    read = await ProgressService(db).read(user_id=funded_account.user_id)

    assert read.rooms[0].challenged == 1
    assert read.rooms[0].held == 0


async def test_a_room_with_nothing_wrong_reads_as_everything_held(
    db, engine, sessions, settlement, funded_account
):
    """The best room somebody has, and the one that would have been invisible.

    Counted from `debriefed_at` rather than from the presence of findings —
    which is the whole reason that column carries a different fact from the
    rows.
    """
    await debriefed(db, engine, sessions, settlement, funded_account)

    read = await ProgressService(db).read(user_id=funded_account.user_id)

    assert read.rooms[0].held == 2
    assert read.rooms[0].challenged == 2


async def test_a_room_nobody_ever_opened_is_not_counted_at_all(
    db, engine, sessions, settlement, funded_account
):
    """The lie the marker exists to prevent.

    A settled room with no reading has no findings, and counting it would report
    a clean sweep for a room the product never assessed. Excluded rather than
    guessed at.
    """
    await room_that_happened(db, engine, sessions, settlement, funded_account, *ROOM)

    read = await ProgressService(db).read(user_id=funded_account.user_id)

    assert read.rooms == ()


async def test_every_room_carries_the_rung_it_was_run_at(
    db, engine, sessions, settlement, funded_account
):
    """The qualifier without which the number lies.

    Difficulty escalates, so a room where more got past somebody may be a room
    that pressed harder. A figure shown without its rung would tell an improving
    presenter they are getting worse — the one message this must never send —
    so the two travel together and are never separable on the wire.

    Null is a real value and stays one: `sessions.difficulty_level` is nullable
    because rooms predating the ladder have no true rung, and writing a
    plausible one would be read as a room that really happened at it.
    """
    session = await debriefed(
        db, engine, sessions, settlement, funded_account, DUCKED
    )
    await db.execute(
        update(SessionModel)
        .where(SessionModel.id == session.id)
        .values(difficulty_level=RELENTLESS)
    )
    await db.commit()

    read = await ProgressService(db).read(user_id=funded_account.user_id)

    assert read.rooms[0].level == RELENTLESS


async def test_it_says_how_they_fail_rather_than_how_much(
    db, engine, sessions, settlement, funded_account
):
    """The half that is actually actionable.

    "Evasive four times in five rooms" tells somebody what to change; a number
    does not. Evasive and contradicted are different faults with different
    fixes — one means you have the answer and are not giving it, the other means
    your figures disagree with each other.

    Only what the presenter was at fault for appears. A habit list naming
    `dismissed` would be a list of things the room did, filed under things they
    do.
    """
    await debriefed(
        db, engine, sessions, settlement, funded_account, DUCKED, TAKEN_AWAY
    )

    read = await ProgressService(db).read(user_id=funded_account.user_id)

    assert dict(read.habits) == {"evasive": 1}


async def test_it_says_who_keeps_catching_them(
    db, engine, sessions, settlement, funded_account
):
    """The other half, and the one somebody can prepare against.

    "The CFO has got past you in every room you have run" is a sentence that
    changes what you rehearse, and it cannot be gamed without actually fixing
    the answer.
    """
    await debriefed(db, engine, sessions, settlement, funded_account, DUCKED)

    read = await ProgressService(db).read(user_id=funded_account.user_id)

    assert dict(read.askers) == {"cfo": 1}


async def test_it_counts_rooms_rather_than_findings(
    db, engine, sessions, settlement, funded_account
):
    """A habit is a thing that recurs, not a thing that happened twice at once.

    Two evasive answers in one bad afternoon is one room where it happened.
    Counting findings would let a single disastrous session look like a pattern,
    which is the opposite of what somebody should take from it.
    """
    twice = (
        DUCKED,
        Judgement(
            ordinal=3,
            quote="What happens when volume triples?",
            weakness=Weakness.EVASIVE,
            why="You asserted it holds without saying what was tested.",
        ),
    )
    await debriefed(db, engine, sessions, settlement, funded_account, *twice)

    read = await ProgressService(db).read(user_id=funded_account.user_id)

    assert dict(read.habits) == {"evasive": 1}


async def test_one_account_never_sees_another_account_s_rooms(
    db, engine, sessions, settlement, funded_account, ledger
):
    """Scoped by the caller's own id, like every other read of somebody's rooms."""
    stranger = await create_funded_account(db, ledger)
    await debriefed(db, engine, sessions, settlement, stranger, DUCKED)

    read = await ProgressService(db).read(user_id=funded_account.user_id)

    assert read.rooms == ()


async def test_an_account_with_no_history_reads_back_empty(db, funded_account):
    """Not an error, and the commonest state there is: a new account.

    Every list empty rather than a refusal, so the screen says "you have not run
    a room yet" instead of "something went wrong".
    """
    read = await ProgressService(db).read(user_id=funded_account.user_id)

    assert read.rooms == ()
    assert read.habits == ()
    assert read.askers == ()




async def test_a_rerun_is_reported_under_the_room_it_repeats(
    db, engine, sessions, settlement, funded_account
):
    """Two attempts at one argument are one rehearsal, and the screen is told so.

    This is the whole difference between "am I getting better" and "am I getting
    better at **this**". Without it the second attempt at a board readout is a
    room that happens to share a panel with an earlier one, and no arithmetic
    downstream can tell three attempts at one argument from three unrelated
    rehearsals.
    """
    first = await debriefed(db, engine, sessions, settlement, funded_account, DUCKED)
    second = await debriefed(
        db, engine, sessions, settlement, funded_account, DUCKED, repeats=first.id
    )

    read = await ProgressService(db).read(user_id=funded_account.user_id)

    assert {room.session_id: room.rehearsal for room in read.rooms} == {
        first.id: first.id,
        second.id: first.id,
    }


async def test_a_room_that_repeats_nothing_is_its_own_rehearsal(
    db, engine, sessions, settlement, funded_account
):
    """Never null on the wire, so a client groups on one field with no special case.

    The column is nullable because a NOT NULL one would have broken inserts from
    the previously deployed build. That is a storage fact, and letting it reach
    a screen would put a null branch in every consumer forever.
    """
    only = await debriefed(db, engine, sessions, settlement, funded_account, DUCKED)

    read = await ProgressService(db).read(user_id=funded_account.user_id)

    assert [room.rehearsal for room in read.rooms] == [only.id]

# --- Over HTTP --------------------------------------------------------------


async def test_progress_is_scoped_to_the_caller_rather_than_to_a_parameter(
    client, db, engine, sessions, settlement, funded_account, bearer, ledger
):
    """An id in the query would be an authorisation check waiting to be forgotten."""
    stranger = await create_funded_account(db, ledger)
    await debriefed(db, engine, sessions, settlement, stranger, DUCKED)
    await debriefed(db, engine, sessions, settlement, funded_account)

    response = await client.get(
        "/v1/progress", headers=bearer(funded_account.user_id)
    )

    assert response.status_code == 200
    assert len(response.json()["rooms"]) == 1
    assert response.json()["habits"] == []


async def test_reading_progress_without_a_credential_reads_nothing(client):
    assert (await client.get("/v1/progress")).status_code == 401


async def test_the_wire_never_separates_a_figure_from_its_rung(
    client, db, engine, sessions, settlement, funded_account, bearer
):
    """The one shape rule this endpoint has.

    `held` and `challenged` mean nothing without `level` — difficulty escalates,
    so a room where more got past somebody may simply be a room that pressed
    harder. Three fields on one object, so a client cannot receive them apart
    and render a trend that tells an improving presenter they are getting worse.
    """
    await debriefed(db, engine, sessions, settlement, funded_account, DUCKED)

    room = (
        await client.get("/v1/progress", headers=bearer(funded_account.user_id))
    ).json()["rooms"][0]

    assert {"held", "challenged", "level"} <= set(room)


async def test_progress_carries_no_transcript_and_no_finding_text(
    client, db, engine, sessions, settlement, funded_account, bearer
):
    """Counts only. `CLAUDE.md` keeps a transcript out of anything list-shaped,
    and a habit tally has no reason to quote a room."""
    await debriefed(db, engine, sessions, settlement, funded_account, DUCKED)

    body = (
        await client.get("/v1/progress", headers=bearer(funded_account.user_id))
    ).text

    assert "grew forty percent" not in body
    assert "feeling about the trend" not in body


async def test_the_wire_names_the_rehearsal_every_room_belongs_to(
    client, db, engine, sessions, settlement, funded_account, bearer
):
    """One field, answered on every room, so a client groups with no null case.

    The column is nullable — a NOT NULL one would have broken inserts from the
    previously deployed build — and that fact stops at the service. A room that
    repeats nothing reports itself.
    """
    first = await debriefed(db, engine, sessions, settlement, funded_account, DUCKED)
    await debriefed(
        db, engine, sessions, settlement, funded_account, DUCKED, repeats=first.id
    )

    rooms = (
        await client.get("/v1/progress", headers=bearer(funded_account.user_id))
    ).json()["rooms"]

    assert {room["rehearsal_id"] for room in rooms} == {str(first.id)}


async def test_the_wire_names_the_rehearsal_when_somebody_named_it(
    client, db, engine, sessions, settlement, funded_account, bearer
):
    """A group headed by a date is honest and nearly useless.

    "Am I getting better at my Q3 board readout" needs the words. The name is
    the lineage's, resolved from whichever room in it was given one, so every
    room in the run reports it — including the ones started before anybody
    thought to name the thing.
    """
    first = await debriefed(db, engine, sessions, settlement, funded_account, DUCKED)
    await debriefed(
        db,
        engine,
        sessions,
        settlement,
        funded_account,
        DUCKED,
        repeats=first.id,
        name="Q3 board readout",
    )

    rooms = (
        await client.get("/v1/progress", headers=bearer(funded_account.user_id))
    ).json()["rooms"]

    assert {room["rehearsal_name"] for room in rooms} == {"Q3 board readout"}


async def test_an_unnamed_rehearsal_says_so_rather_than_inventing_a_heading(
    client, db, engine, sessions, settlement, funded_account, bearer
):
    """Null, so the screen can head the run with a date instead.

    Deriving a name from the panel or the deck would put a label on a run the
    presenter never chose, and they would then have no way to correct it.
    """
    await debriefed(db, engine, sessions, settlement, funded_account, DUCKED)

    rooms = (
        await client.get("/v1/progress", headers=bearer(funded_account.user_id))
    ).json()["rooms"]

    assert rooms[0]["rehearsal_name"] is None
