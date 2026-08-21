"""What a debrief knows when it opens, and what it costs to know it.

`docs/debrief-and-sparring.md` decision 1: weak answers are born when the
debrief opens, written once, and read by everything downstream — the coach, the
prep sheet, and #55's calibration. Not at settlement, which has four callers and
is the billing-close path; not live, which spends latency inside the metered
phase on something nobody hears.

Decision 7 settles which rooms earn one at all.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.billing.models import Account

from app.agents.context import USER, Said
from app.agents.difficulty import GENTLE, RELENTLESS
from app.agents.model import TurnUsage
from app.agents.weakness import Judgement, Weakness, WeaknessReading
from app.core.errors import FlintroomError
from app.modules.sessions.debrief import DebriefService
from app.modules.sessions.models import Session, SessionWeakAnswer
from app.modules.sessions.schemas import EndReason
from app.modules.sessions.transcript import SessionTranscript


class CountingReader:
    """Answers from a script, and records how often it was asked."""

    def __init__(self, *judged: Judgement) -> None:
        self._judged = judged
        self.calls = 0

    async def rank(self, *, room):
        self.calls += 1
        return WeaknessReading(judged=self._judged, usage=TurnUsage(1200, 300))


class Rendezvous(CountingReader):
    """A reader that will not answer until both callers have asked.

    Without it the race does not happen: `asyncio.gather` starts the first
    coroutine, and everything before the commit is fast enough that it finishes
    before the second one checks whether the room has been read. The second then
    takes the cached path and the claim is never contested — the test passes
    while proving nothing, which is exactly how the mutation survived.

    The barrier holds both inside the model call, which is where a real pair of
    devices would be: past the "already read" check, before either has written.
    """

    def __init__(self, *judged) -> None:
        super().__init__(*judged)
        self._both = asyncio.Barrier(2)

    async def rank(self, *, room):
        reading = await super().rank(room=room)
        await self._both.wait()
        return reading


async def room_that_happened(
    db,
    engine,
    sessions,
    settlement,
    account,
    *lines: Said,
    ended=EndReason.USER_ENDED,
    repeats=None,
):
    """A settled session with these lines in its transcript.

    `repeats` names the room this one is another attempt at, so a test can build
    a rehearsal rather than a scattering of unrelated rooms.
    """
    session = await sessions.start(user_id=account.user_id, repeats=repeats)
    await sessions.activate(session_id=session.id)
    await db.commit()

    transcript = SessionTranscript(
        async_sessionmaker(engine, expire_on_commit=False), session_id=session.id
    )
    for line in lines:
        await transcript.record(line)

    await settlement.close(session_id=session.id, end_reason=ended)
    return session


#: One finding, for tests that need a room to have produced something.
CAUGHT = Judgement(
    ordinal=1,
    quote="Off what base, and at what cost?",
    weakness=Weakness.EVASIVE,
    why="You answered with a feeling about the trend, not a base.",
)

ROOM = (
    Said(speaker=USER, text="We grew forty percent last quarter."),
    Said(speaker="cfo", text="Off what base, and at what cost?"),
    Said(speaker=USER, text="We are really pleased with the trajectory."),
)


async def test_a_room_is_read_once_and_the_answer_is_kept(
    db, engine, sessions, settlement, funded_account
):
    """The tracer bullet, and the idempotency that makes decision 1 affordable.

    A reasoning model reading a whole room is the most expensive single call in
    the product outside the room itself, and the debrief is unmetered — so a
    second open must not buy a second reading. That is not only cost: the
    ordering moves between runs on the same transcript, so a list recomputed on
    every open would reshuffle under a user who is working through it, and the
    prep sheet they screenshotted would stop matching the screen.

    Asserted on the call count as well as on equality, because a service that
    re-read the room and happened to get the same scripted answer back would
    look identical from outside.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    reader = CountingReader(
        Judgement(
            ordinal=1,
            quote="Off what base, and at what cost?",
            weakness=Weakness.EVASIVE,
            why="You answered with a feeling about the trend, not a base.",
        )
    )
    service = DebriefService(db, reader=reader)

    first = await service.weak_answers(session_id=session.id)
    second = await service.weak_answers(session_id=session.id)

    assert reader.calls == 1
    assert first == second
    assert [(a.ordinal, a.weakness) for a in first] == [(1, Weakness.EVASIVE)]
    assert first[0].question == "Off what base, and at what cost?"
    assert first[0].answer == "We are really pleased with the trajectory."


async def test_a_room_the_panel_never_spoke_in_has_nothing_to_debrief(
    db, engine, sessions, settlement, funded_account
):
    """Decision 7's floor, and it is not the same as finding nothing.

    An empty list means *"you did well"*. This means *"there is no session
    here"* — the panel never asked, so the coach has nothing to be grounded in,
    and a coach with nothing to cite has to invent. CLAUDE.md refuses that
    outright, so the refusal belongs here rather than three layers downstream in
    a prompt that has already been handed an empty room.

    Refused before the reader is called. That is the assertion worth making: a
    version that read the room first and returned nothing would look correct and
    would spend a reasoning-model call on a transcript with no questions in it.
    """
    session = await room_that_happened(
        db,
        engine,
        sessions,
        settlement,
        funded_account,
        Said(speaker=USER, text="Hello? Is this thing on?"),
    )
    reader = CountingReader()

    with pytest.raises(FlintroomError) as refused:
        await DebriefService(db, reader=reader).weak_answers(session_id=session.id)

    assert refused.value.status_code == 422
    assert reader.calls == 0


async def test_a_room_still_running_is_not_debriefed(
    db, engine, sessions, funded_account
):
    """§4.1 puts settlement first: the panel finishes, then the debrief opens.

    Reading a live room would rank a conversation still happening, and would do
    it against a transcript that is still being written — so the same session
    would produce a different list a minute later, having already stored the
    first one.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await sessions.activate(session_id=session.id)
    await db.commit()

    reader = CountingReader()

    with pytest.raises(FlintroomError) as refused:
        await DebriefService(db, reader=reader).weak_answers(session_id=session.id)

    assert refused.value.status_code == 409
    assert reader.calls == 0


async def test_a_room_the_product_broke_offers_a_fresh_one_instead(
    db, engine, sessions, settlement, funded_account
):
    """Decision 7: when the provider failed, the minutes are already back.

    A restart is both cheaper for the user and more honest than coaching them
    through a session the product broke — and reading it would produce a
    debrief about a room that stopped mid-sentence for reasons that were never
    theirs.

    Deliberately NOT keyed on `REFUND_REASONS`, which is the obvious thing to
    reuse and would be wrong. It holds two entries, and they mean opposite
    things here: `IDLE_TIMEOUT` is also refunded, and a room that ended because
    the presenter sat in silence for ninety seconds has plenty to debrief — that
    silence is the most eloquent dodge available, and `annotate` already treats
    it as one. Refunding is about the money; this is about whose fault it was.
    """
    session = await room_that_happened(
        db,
        engine,
        sessions,
        settlement,
        funded_account,
        Said(speaker=USER, text="We grew forty percent."),
        Said(speaker="cfo", text="Off what base?"),
        ended=EndReason.PROVIDER_FAILURE,
    )
    reader = CountingReader()

    with pytest.raises(FlintroomError) as refused:
        await DebriefService(db, reader=reader).weak_answers(session_id=session.id)

    assert refused.value.code == "room_broke"
    assert reader.calls == 0


async def test_ninety_seconds_of_silence_still_earns_a_debrief(
    db, engine, sessions, settlement, funded_account
):
    """The other refunded reason, and it must not be swept up with the first.

    A room ended by `IDLE_TIMEOUT` is refunded — the money is not owed — and it
    is *also* the room with the most to say. The presenter was asked something
    and said nothing for a minute and a half, which is exactly the substance a
    debrief exists to surface. Refusing it would refund the user and then hide
    the reason.
    """
    session = await room_that_happened(
        db,
        engine,
        sessions,
        settlement,
        funded_account,
        Said(speaker=USER, text="We grew forty percent."),
        Said(speaker="cfo", text="Off what base?"),
        ended=EndReason.IDLE_TIMEOUT,
    )
    reader = CountingReader(
        Judgement(
            ordinal=1,
            quote="Off what base?",
            weakness=Weakness.UNANSWERED,
            why="You went quiet rather than giving the number.",
        )
    )

    found = await DebriefService(db, reader=reader).weak_answers(session_id=session.id)

    assert [a.weakness for a in found] == [Weakness.UNANSWERED]


async def test_the_ranking_reads_back_in_the_order_the_model_chose(
    db, engine, sessions, settlement, funded_account
):
    """The order is the answer, not a presentation detail.

    §3.5 asks for a *ranked* list, and the rank was decided with the whole room
    in view by the only thing that read it. Storage that returned the same
    findings in a different order would be returning a different answer to the
    question that was asked — and it would do it invisibly, because every
    individual finding would still be correct.

    Two items, deliberately: one cannot be out of order. The first read comes
    from the reader and the second from the database, so both paths are asserted
    to agree — a service that ordered correctly on the way in and read back by
    insertion order would pass with one item and fail in production.
    """
    session = await room_that_happened(
        db,
        engine,
        sessions,
        settlement,
        funded_account,
        Said(speaker=USER, text="Margin is seventy."),
        Said(speaker="cfo", text="Off what base?"),
        Said(speaker=USER, text="It has been strong."),
        Said(speaker="technical_skeptic", text="And latency at ten times load?"),
        Said(speaker=USER, text="We are excited about the roadmap."),
    )
    service = DebriefService(
        db,
        reader=CountingReader(
            Judgement(
                ordinal=3,
                quote="And latency at ten times load?",
                weakness=Weakness.EVASIVE,
                why="You answered with enthusiasm rather than a number.",
            ),
            Judgement(
                ordinal=1,
                quote="Off what base?",
                weakness=Weakness.UNSUPPORTED,
                why="Strong is not a base.",
            ),
        ),
    )

    fresh = await service.weak_answers(session_id=session.id)
    stored = await service.weak_answers(session_id=session.id)

    assert [a.ordinal for a in fresh] == [3, 1]
    assert [a.ordinal for a in stored] == [3, 1]


async def test_the_stored_ranking_is_ordered_by_rank_and_not_by_luck(
    db, engine, sessions, settlement, funded_account
):
    """Written after the obvious version of this test failed to catch anything.

    `test_the_ranking_reads_back_in_the_order_the_model_chose` passes with the
    `ORDER BY` deleted. Rows are inserted in rank order, so Postgres returns
    them in rank order, and the read looks correct for a reason that has nothing
    to do with the query — a coincidence that survives exactly until a row is
    updated or the table stops fitting on one page.

    Writing them out of order is not enough on its own either — that was the
    second attempt. The primary key is `(session_id, rank)`, so Postgres
    satisfies the `WHERE` with an index scan and hands back rank order for free;
    the clause is right and unfalsifiable at the same time. The planner is
    therefore pushed off the index here, which is the only arrangement where
    deleting the `ORDER BY` actually breaks anything.

    Worth the two extra lines because the ranking *is* the answer §3.5 asks for,
    and the failure would be silent: every individual finding correct, the list
    in an order nobody chose.
    """
    session = await room_that_happened(
        db,
        engine,
        sessions,
        settlement,
        funded_account,
        Said(speaker=USER, text="Margin is seventy."),
        Said(speaker="cfo", text="Off what base?"),
    )

    for rank in (2, 0, 1):
        db.add(
            SessionWeakAnswer(
                session_id=session.id,
                rank=rank,
                ordinal=1,
                question="Off what base?",
                asked_by="cfo",
                answer=None,
                weakness=Weakness.UNSUPPORTED.value,
                why=f"finding number {rank}",
            )
        )
    # Marked read, because a real read is what wrote those rows. Without it the
    # service correctly treats the room as never opened and hands back the
    # scripted reader's empty list — which is #57's caching working, not the
    # ordering under test.
    await db.execute(
        update(Session).where(Session.id == session.id).values(debriefed_at=func.now())
    )
    await db.commit()

    # Heap order, not index order — and set AFTER the commit, which is the part
    # that took three attempts. `SET LOCAL` dies with the transaction that set
    # it, so configuring it before the write leaves the *read* on default
    # settings, answering from the primary key and coming back sorted whatever
    # the ORDER BY says. Verified against EXPLAIN: index scan before, seq scan
    # after.
    await db.execute(text("SET LOCAL enable_indexscan = off"))
    await db.execute(text("SET LOCAL enable_bitmapscan = off"))

    found = await DebriefService(db, reader=CountingReader()).weak_answers(
        session_id=session.id
    )

    assert [a.why for a in found] == [
        "finding number 0",
        "finding number 1",
        "finding number 2",
    ]


async def test_reading_the_room_moves_the_rung_the_next_one_is_on(
    db, engine, sessions, settlement, funded_account
):
    """#55, and the only place the level is ever written by the system.

    Here rather than at settle because this is where the reading exists.
    `docs/difficulty-calibration.md` decision 7 is explicit that a room nobody
    debriefed moves nothing: there is no signal, and inventing one would move
    somebody's level on a reading nobody made.

    One question, none of them fumbled, so the room was handled and the next
    one is harder.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    before = await _level(db, funded_account.user_id)

    await DebriefService(db, reader=CountingReader()).weak_answers(
        session_id=session.id
    )

    assert await _level(db, funded_account.user_id) == before + 1


async def test_opening_the_debrief_twice_does_not_move_it_twice(
    db, engine, sessions, settlement, funded_account
):
    """The rung follows the reading, and the reading happens once.

    A user working through their weak answers reopens the screen; a second
    device opens it at the same moment. Neither is a second session and neither
    is evidence of anything, so a level that climbed on every open would
    escalate on nothing but attention — and would do it fastest for exactly the
    people engaging most with the coaching.

    Bound to the write that wins the insert rather than checked separately: the
    weak answers and the rung are one fact about one reading, and two guards
    could disagree.
    """
    service = DebriefService(db, reader=CountingReader())
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )

    await service.weak_answers(session_id=session.id)
    once = await _level(db, funded_account.user_id)
    await service.weak_answers(session_id=session.id)

    assert await _level(db, funded_account.user_id) == once


async def _level(db, user_id) -> int:
    """Read past the identity map — the service commits, which expires it."""
    stored = await db.execute(
        select(Account.difficulty_level).where(Account.user_id == user_id)
    )
    return stored.scalar_one()


async def test_a_flawless_room_is_also_read_only_once(
    db, engine, sessions, settlement, funded_account
):
    """The case #57's caching misses, and it is the cheapest room to get wrong.

    `_kept` decides "already read" by whether any rows came back, so a room the
    model found nothing wrong with is indistinguishable from one nobody has
    read. Every open buys another reasoning-model pass over the whole
    transcript — the most expensive single call outside the room itself, on the
    phase §4.1 promises is unmetered.

    The existing tracer scripts a reader that finds one weak answer, so it
    never touches this path.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    reader = CountingReader()
    service = DebriefService(db, reader=reader)

    await service.weak_answers(session_id=session.id)
    await service.weak_answers(session_id=session.id)

    assert reader.calls == 1


async def test_a_room_they_fumbled_softens_the_next_one(
    db, engine, sessions, settlement, funded_account
):
    """The direction Open Risk #1 is actually about, end to end.

    Also pins the denominator. The room has one panel question and two lines
    from the presenter; counting every transcript line instead would put one
    fumbled answer at a third rather than at all of them, land it between both
    thresholds, and quietly turn calibration into a mechanism that almost never
    softens anything.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    await db.execute(
        update(Account)
        .where(Account.user_id == funded_account.user_id)
        .values(difficulty_level=RELENTLESS)
    )
    await db.commit()

    await DebriefService(
        db,
        reader=CountingReader(
            Judgement(
                ordinal=1,
                quote="Off what base, and at what cost?",
                weakness=Weakness.EVASIVE,
                why="You answered with a feeling about the trend, not a base.",
            )
        ),
    ).weak_answers(session_id=session.id)

    assert await _level(db, funded_account.user_id) == RELENTLESS - 1


async def test_two_devices_opening_at_once_read_the_room_once(
    db, engine, sessions, settlement, funded_account
):
    """The claim's whole reason to exist, and the only way to reach it.

    A sequential second open never gets here — `_read_already` sends it
    straight to the stored list. This is the case that does: two phones on the
    debrief screen at the same moment, both past that check because neither
    transaction has committed yet.

    The loser's `UPDATE ... WHERE debriefed_at IS NULL` blocks on the row lock
    until the winner commits, then re-evaluates the condition and matches
    nothing. That is what makes it a guard rather than a check, and it is the
    reason the level cannot move twice for one room: the calibration sits after
    the claim in the same transaction.

    Two writers rather than twenty, because unlike a lost update this fails at
    two or not at all.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    session_id = session.id
    factory = async_sessionmaker(engine, expire_on_commit=False)
    # A reader that finds nothing, so the rung moves *up*. A fumbled room would
    # move it down, and the account is already on the floor — the clamp would
    # make one move and two moves look identical, which is the whole thing
    # under test.
    reader = Rendezvous()

    async def open_debrief():
        async with factory() as fresh:
            return await DebriefService(fresh, reader=reader).weak_answers(
                session_id=session_id
            )

    both = await asyncio.gather(open_debrief(), open_debrief())

    # Both callers get the same list — the loser hands back the winner's.
    assert both[0] == both[1]
    # And the rung moved once, not twice, for one room.
    assert await _level(db, funded_account.user_id) == GENTLE + 1
    # Both *did* read the room, and that is accepted rather than prevented: the
    # wasted model call is the price of not holding a lock across it. What must
    # not happen twice is the write.
    assert reader.calls == 2


async def test_reading_a_room_records_that_it_was_read(
    db, engine, sessions, settlement, funded_account
):
    """`debriefed_at` from the outside, which nothing else asserted.

    The column has existed since it was added for the read-once guard, and its
    own docstring gives the reason: *"a column rather than 'are there any rows',
    because an empty list is a real answer"*. Every test until now exercised it
    through the guard — how many times the reader was called — so the marker
    itself was only ever observed by its side effect.

    Asserted directly because progress reads it for a different purpose: it is
    what separates a room with nothing wrong from a room nobody opened, and a
    figure built on the wrong one of those is a figure nobody should trust.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    assert (await sessions.get(session_id=session.id)).debriefed_at is None

    await DebriefService(db, reader=CountingReader(CAUGHT)).weak_answers(
        session_id=session.id
    )

    assert (await sessions.get(session_id=session.id)).debriefed_at is not None


async def test_a_room_with_nothing_wrong_is_still_recorded_as_read(
    db, engine, sessions, settlement, funded_account
):
    """The case the column exists for, stated as a fact about the room.

    A presenter who answered everything well leaves no findings. Counted by
    rows, their best room would be invisible to progress — which inverts the
    signal exactly where somebody most wants to see it.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )

    await DebriefService(db, reader=CountingReader()).weak_answers(
        session_id=session.id
    )

    assert (await sessions.get(session_id=session.id)).debriefed_at is not None


async def test_reading_a_room_twice_keeps_the_first_reading_time(
    db, engine, sessions, settlement, funded_account
):
    """When the room was assessed, not when it was last looked at.

    A phone re-fetches on every resume. A marker that moved would make "when did
    I work on this" unanswerable and would make the ordering of a history depend
    on which rooms somebody happened to reopen.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    service = DebriefService(db, reader=CountingReader(CAUGHT))

    await service.weak_answers(session_id=session.id)
    first = (await sessions.get(session_id=session.id)).debriefed_at

    await service.weak_answers(session_id=session.id)

    assert (await sessions.get(session_id=session.id)).debriefed_at == first


async def test_a_marker_lost_without_its_rows_costs_nothing_and_answers(
    db, engine, sessions, settlement, funded_account
):
    """Reported as a 500 from a phone on 2026-08-20, and it is a real hole.

    `debriefed_at` and the stored rows are two records of one fact, and this is
    what happens when they disagree: the marker was null, the rows were there,
    so the service ran the reasoning model again — a real Gemini call, billed —
    claimed the marker, and then tried to insert rank 0 over a rank 0 that
    already existed. `UniqueViolationError`, unhandled, 500. Every subsequent
    open would have done the same, forever, and each one would have cost
    another reading.

    I put that room into that state by clearing `debriefed_at` so its opening
    would speak again, which is exactly the kind of thing an operator or a
    restored backup does.

    **The kept rows are the truth.** They are what the user was shown and what
    the prep sheet they screenshotted was built from. A fresh reading would
    reorder under somebody working through it — the failure
    `test_a_room_is_read_once_and_the_answer_is_kept` exists to prevent — so the
    fix is to answer from the rows and never open the model at all.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    reader = CountingReader(
        Judgement(
            ordinal=1,
            quote="Off what base, and at what cost?",
            weakness=Weakness.EVASIVE,
            why="You answered with a feeling about the trend, not a base.",
        )
    )
    service = DebriefService(db, reader=reader)
    first = await service.weak_answers(session_id=session.id)

    # The marker goes, the rows stay — an operator, or a partly restored backup.
    await db.execute(
        update(Session).where(Session.id == session.id).values(debriefed_at=None)
    )
    await db.commit()

    again = await service.weak_answers(session_id=session.id)

    assert again == first
    assert reader.calls == 1, "a lost marker must not buy a second reading"


async def test_the_marker_is_put_back_when_the_rows_outlive_it(
    db, engine, sessions, settlement, funded_account
):
    """Answering is not enough — the state has to stop being wrong.

    Leaving `debriefed_at` null would make every open take the recovery path
    forever, and Progress counts assessed rooms by that column, so the room
    would stay missing from somebody's record.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    service = DebriefService(
        db,
        reader=CountingReader(
            Judgement(
                ordinal=1,
                quote="Off what base, and at what cost?",
                weakness=Weakness.EVASIVE,
                why="You answered with a feeling about the trend, not a base.",
            )
        ),
    )
    await service.weak_answers(session_id=session.id)
    await db.execute(
        update(Session).where(Session.id == session.id).values(debriefed_at=None)
    )
    await db.commit()

    await service.weak_answers(session_id=session.id)

    mark = await db.scalar(
        select(Session.debriefed_at).where(Session.id == session.id)
    )
    assert mark is not None
