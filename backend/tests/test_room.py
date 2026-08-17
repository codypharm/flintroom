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
