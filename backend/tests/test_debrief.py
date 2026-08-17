"""What a debrief knows when it opens, and what it costs to know it.

`docs/debrief-and-sparring.md` decision 1: weak answers are born when the
debrief opens, written once, and read by everything downstream — the coach, the
prep sheet, and #55's calibration. Not at settlement, which has four callers and
is the billing-close path; not live, which spends latency inside the metered
phase on something nobody hears.

Decision 7 settles which rooms earn one at all.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.context import USER, Said
from app.agents.model import TurnUsage
from app.agents.weakness import Judgement, Weakness, WeaknessReading
from app.core.errors import FlintroomError
from app.modules.sessions.debrief import DebriefService
from app.modules.sessions.models import SessionWeakAnswer
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


async def room_that_happened(
    db, engine, sessions, settlement, account, *lines: Said, ended=EndReason.USER_ENDED
):
    """A settled session with these lines in its transcript."""
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await db.commit()

    transcript = SessionTranscript(
        async_sessionmaker(engine, expire_on_commit=False), session_id=session.id
    )
    for line in lines:
        await transcript.record(line)

    await settlement.close(session_id=session.id, end_reason=ended)
    return session


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
