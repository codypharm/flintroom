"""Building the room a live socket actually gets.

The join everything else has been waiting on. Panel seating, selection,
composition, casting, transcription and barge-in have all existed and been
tested in isolation; nothing assembled them into something a phone could reach.
Until this, a live session dialled ElevenLabs Agents — one remote agent, one
voice, a persona configured in somebody else's dashboard — and none of
`app/agents/` was reachable from a socket at all.

`OrchestratedProvider` is per room rather than per process, because which
archetypes are seated and which deck they may attack are facts about one
session. That is the asymmetry this module exists to absorb.
"""

from __future__ import annotations

import pytest

from app.core.errors import ProviderUnavailable
from app.modules.sessions.service import SessionService
from sqlalchemy import select, update

from app.agents.difficulty import GENTLE, RELENTLESS, pressure_at
from app.modules.billing.models import Account
from app.modules.sessions.models import Session
from app.modules.voice.room import build_room

pytestmark = pytest.mark.asyncio


# Deliberately inert. `build_room` composes these rather than calling them —
# what it decides is which seats and which claims the room gets, and a fake that
# could hold a conversation would only make that harder to see. The loop itself
# is exercised in `test_orchestrated_channel.py`.


class FakeTranscriber:
    def open(self):  # pragma: no cover - never dialled here
        raise NotImplementedError


class FakePanelModel:
    async def select(self, *, candidates, context):  # pragma: no cover
        raise NotImplementedError

    async def compose(self, *, archetype, context, finding=None, dispute=None):  # pragma: no cover
        raise NotImplementedError


async def test_the_room_seats_the_panel_the_session_was_started_with(db, funded_account):
    """A socket gets the archetypes chosen at start, in seat order.

    Order carries meaning — `routing.choose` breaks ties on panel index — so a
    room rebuilt in a different order is a different room. This is the assertion
    that the seats survive the trip from the database to the thing holding the
    conversation.
    """
    session = await SessionService(db).start(
        user_id=funded_account.user_id,
        archetypes=["technical_skeptic", "champion", "cfo"],
    )

    room = await build_room(
        db,
        session_id=session.id,
        user_id=funded_account.user_id,
        transcriber=FakeTranscriber(),
        model=FakePanelModel(),
    )

    assert [archetype.name for archetype in room.panel] == [
        "technical_skeptic",
        "champion",
        "cfo",
    ]


async def test_a_deployment_that_cannot_hear_refuses_the_room(db, funded_account):
    """No transcriber means no interrogation, and it must fail before billing.

    A room that opened without one would transcribe nothing, so no panelist
    would ever speak — and the meter would run against silence while the user
    waited for a question. Refusing here surfaces as the typed, unnamed failure
    the relay already knows how to settle and refund against.
    """
    session = await SessionService(db).start(user_id=funded_account.user_id)

    with pytest.raises(ProviderUnavailable):
        await build_room(
            db,
            session_id=session.id,
            user_id=funded_account.user_id,
            transcriber=None,
            model=FakePanelModel(),
        )


async def test_a_deployment_with_no_panel_model_refuses_the_room(db, funded_account):
    """Same story as the transcriber, at the other end of the turn.

    A room that can hear and cannot compose is worse than one that refuses: it
    bills, it listens, and it never answers. Silence is indistinguishable from a
    slow model from the user's side of a phone lying on a desk.
    """
    session = await SessionService(db).start(user_id=funded_account.user_id)

    with pytest.raises(ProviderUnavailable):
        await build_room(
            db,
            session_id=session.id,
            user_id=funded_account.user_id,
            transcriber=FakeTranscriber(),
            model=None,
        )


async def test_a_room_without_a_speaker_is_a_legitimate_deployment(db, funded_account):
    """A silent panel still routes, composes and captions.

    Unlike the two above, this one degrades rather than refuses. Captions are a
    v1 accessibility requirement in their own right — `CLAUDE.md` sets the floor
    at WCAG 2.2 AA *plus live captions* — so a room with no synthesiser is
    missing its voice, not its function, and a local deployment without an
    ElevenLabs key can still exercise the whole loop.
    """
    session = await SessionService(db).start(user_id=funded_account.user_id)

    room = await build_room(
        db,
        session_id=session.id,
        user_id=funded_account.user_id,
        transcriber=FakeTranscriber(),
        model=FakePanelModel(),
        speaker=None,
    )

    assert room.panel


async def test_the_room_is_built_at_the_rung_the_account_is_on(db, funded_account):
    """#55, and the only place the stored number becomes a room.

    Read here rather than at session start because this is where a room is
    assembled and where `user_id` is already in hand. It is also the moment
    that matters: a level changed between starting a session and joining it
    should take effect on the room that actually happens.

    A user's very first room is gentle, from the column default, with no
    lookup and no first-run branch to be wrong about.
    """
    session = await SessionService(db).start(user_id=funded_account.user_id)

    gentle = await build_room(
        db,
        session_id=session.id,
        user_id=funded_account.user_id,
        transcriber=FakeTranscriber(),
        model=FakePanelModel(),
    )
    assert gentle.pressure == pressure_at(GENTLE)

    await db.execute(
        update(Account)
        .where(Account.user_id == funded_account.user_id)
        .values(difficulty_level=RELENTLESS)
    )
    await db.commit()

    hardened = await build_room(
        db,
        session_id=session.id,
        user_id=funded_account.user_id,
        transcriber=FakeTranscriber(),
        model=FakePanelModel(),
    )
    assert hardened.pressure == pressure_at(RELENTLESS)


async def test_the_room_records_the_rung_it_actually_ran_at(db, funded_account):
    """What room did this person get? Nothing could answer that until now.

    Written where the rung is resolved, so the record and the room cannot
    disagree. Its first consumer is the debrief's one sentence — "they pressed
    harder this time than last" is a comparison, and a comparison needs the
    other side stored — but the column earns its place beyond that: #14 has to
    reconcile cost against what actually happened, and until this existed every
    settled session looked identical.

    Null until a room is assembled, not defaulted to a rung. A session that was
    started and never joined ran at no difficulty at all, and recording a
    plausible one would be inventing a room that did not happen.
    """
    session = await SessionService(db).start(user_id=funded_account.user_id)
    assert await _rung_on(db, session.id) is None

    await db.execute(
        update(Account)
        .where(Account.user_id == funded_account.user_id)
        .values(difficulty_level=RELENTLESS)
    )
    await db.commit()

    await build_room(
        db,
        session_id=session.id,
        user_id=funded_account.user_id,
        transcriber=FakeTranscriber(),
        model=FakePanelModel(),
    )

    assert await _rung_on(db, session.id) == RELENTLESS


async def _rung_on(db, session_id):
    stored = await db.execute(
        select(Session.difficulty_level).where(Session.id == session_id)
    )
    return stored.scalar_one()
