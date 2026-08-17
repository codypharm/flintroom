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
