"""What the room said, after the room is over.

The transcript is the first thing Flintroom keeps. Everything before it was
either money (`ledger_entries`), proof (`audit_events`) or telemetry
(`session_costs`) — none of it content, and none of it something a user would
recognise as theirs.

`docs/session-retention.md` settles what that means: text survives on every tier
for the life of the account, because `Product.md` §405 grounds the coach in it
and `CLAUDE.md` requires that scope to be structural rather than a system prompt.
A debrief cannot be constrained to a transcript it cannot read.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.context import USER, Said
from app.modules.sessions.transcript import SessionTranscript
from app.modules.voice.transcript import TranscriptStore

pytestmark = pytest.mark.asyncio


async def test_a_room_reads_back_in_the_order_it_happened(
    db, engine, sessions, funded_account
):
    """Order is the content, not a presentation detail.

    A transcript is a sequence of pairs — what was put to the user and what came
    back — and `Product.md` §3.5 ranks weak *answers*, which is a judgement about
    a pair. The same lines in the wrong order describe a different room: a
    panelist answered before they asked, a user conceding a point nobody had
    made yet.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    # Committed on purpose, and it is the point rather than setup noise: the
    # store writes on its own connection, so it can only see a session that is
    # actually there. A room whose row was still uncommitted would fail the
    # foreign key on its first line.
    await db.commit()

    transcript = SessionTranscript(
        async_sessionmaker(engine, expire_on_commit=False), session_id=session.id
    )

    await transcript.record(Said(speaker=USER, text="Our gross margin is seventy percent."))
    await transcript.record(Said(speaker="cfo", text="The deck says sixty-one."))
    await transcript.record(Said(speaker=USER, text="Blended, across both lines."))

    assert await transcript.lines() == (
        Said(speaker=USER, text="Our gross margin is seventy percent."),
        Said(speaker="cfo", text="The deck says sixty-one."),
        Said(speaker=USER, text="Blended, across both lines."),
    )


async def test_a_line_that_took_issue_with_a_colleague_reads_back_as_one(
    db, engine, sessions, funded_account
):
    """The flag is only useful if it survives the write.

    Everything upstream of here already carries it — `PanelTurn.disputed` from
    #54's gate, `Said.disputed` through the channel — and none of that reaches
    the debrief, which reads rows rather than objects. A column left off would
    lose the fact at exactly the boundary where it stops being recoverable: once
    the room is over, a disputing line and an ordinary one are the same text by
    the same speaker in the same position.

    What it costs to lose is not a feature. `weakness.py` reads this flag to tell
    a question a colleague talked over from one the presenter ducked, and only
    one of those is the user's fault.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await db.commit()

    transcript = SessionTranscript(
        async_sessionmaker(engine, expire_on_commit=False), session_id=session.id
    )

    await transcript.record(Said(speaker="champion", text="Who will sponsor this?"))
    await transcript.record(
        Said(speaker="cfo", text="The debt matters more. What does it cost?", disputed=True)
    )

    assert await transcript.lines() == (
        Said(speaker="champion", text="Who will sponsor this?"),
        Said(speaker="cfo", text="The debt matters more. What does it cost?", disputed=True),
    )


async def test_what_handed_a_panelist_the_floor_reads_back_too(
    db, engine, sessions, funded_account
):
    """A finding routes one turn and is then gone.

    Nothing persists a `Finding` — it is read from one utterance, decides who
    speaks next, and is discarded. So the routing reason on the line it produced
    is the only surviving evidence that the Auditor caught a contradiction, and
    `weakness.py` ranks on exactly that.

    `None` for the user's own line, because nobody chose it. Asserted here rather
    than assumed: a column defaulting to `"model"` would quietly claim the
    selection model had spoken for every sentence the presenter said, and the
    room's health metric is a ratio over that field.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await db.commit()

    transcript = SessionTranscript(
        async_sessionmaker(engine, expire_on_commit=False), session_id=session.id
    )

    await transcript.record(Said(speaker=USER, text="Margin is seventy."))
    await transcript.record(
        Said(speaker="cfo", text="You said sixty-one before.", chosen_by="finding")
    )

    assert [line.chosen_by for line in await transcript.lines()] == [None, "finding"]


async def test_the_store_still_fits_the_seam_the_room_writes_through():
    """A guard, not a driver — and the one the `Protocol` exists to make possible.

    `TranscriptStore` is `runtime_checkable` for the reason `TranscriptionStream`
    is: there is no base class to inherit and no type checker in the suite, so
    renaming `record` here would stay green everywhere and fail only when a live
    room tried to write its first line — by which point the user is already
    talking.

    Proves the methods exist and nothing about their signatures, which is exactly
    the class of mistake nothing else here would catch.
    """
    assert isinstance(SessionTranscript(None, session_id=uuid.uuid4()), TranscriptStore)
