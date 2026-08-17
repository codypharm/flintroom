"""The socket, end to end, against the room it now opens.

Nothing exercised this route before. Every part below it had tests — tickets,
relay, orchestration, panel, transcription — and the one line joining them did
not, which is exactly where wiring goes wrong: a route that builds the wrong
object still typechecks, still starts, and fails only on a phone.

The websocket is faked rather than driven through `TestClient`. The db fixture
is an `AsyncSession` inside a transaction on this event loop, and `TestClient`
runs the app on another one — so the choice is between a fake socket and a
second database story. The socket is a boundary; the wiring is not.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import WebSocketDisconnect
from sqlalchemy import select

from app.agents.model import ModelReply
from app.core.errors import ProviderUnavailable
from app.modules.sessions.schemas import EndReason, SessionState
from app.modules.sessions.service import SessionService
from app.modules.voice.dependencies import RoomParts
from app.agents.context import USER, Said
from app.modules.sessions.transcript import SessionTranscript
from app.modules.voice.router import CLOSE_PROVIDER_UNAVAILABLE, stream_session
from app.modules.voice.costs import SessionCost
from app.modules.voice.tickets import VoiceTicketService
from app.modules.voice.transcription import Transcription

pytestmark = pytest.mark.asyncio

LINE = "Where does sixty-one percent come from?"


class FakeTranscriptionStream:
    """One utterance, then the room goes quiet."""

    def __init__(self, said: str) -> None:
        self._said = said

    async def send_audio(self, pcm: bytes) -> None:
        pass

    async def results(self):
        yield Transcription(text=self._said, final=True)


class FakeTranscriber:
    def __init__(self, said: str = "Our gross margin is sixty-one percent.") -> None:
        self._said = said

    @asynccontextmanager
    async def open(self):
        yield FakeTranscriptionStream(self._said)


class FakePanelModel:
    """Picks a named seat and writes one line for it."""

    def __init__(self, *, selects: str) -> None:
        self._selects = selects
        self.wrote_as: list[str] = []
        self.composed_with: list = []

    async def select(self, *, candidates, context) -> ModelReply:
        return ModelReply(text=self._selects)

    async def compose(self, *, archetype, context, finding=None, dispute=None) -> ModelReply:
        self.wrote_as.append(archetype.name)
        self.composed_with.append(context)
        return ModelReply(text=LINE)


class FakeWebSocket:
    """A phone that hangs up once the panel has said something.

    Holding the connection open until then is the point: the relay pumps client
    audio and channel events concurrently, so a socket that disconnected
    immediately would race the turn and pass or fail on scheduling rather than
    on behaviour.
    """

    def __init__(self, *, hangs_up: str = "after_transcript") -> None:
        self.accepted = False
        self.closed_with: int | None = None
        self.transcripts: list[str] = []
        self.audio_sent: list[bytes] = []
        self._spoken = asyncio.Event()
        self._hangs_up = hangs_up

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code

    async def send_bytes(self, pcm: bytes) -> None:
        self.audio_sent.append(pcm)

    async def send_json(self, message: dict) -> None:
        if message.get("type") == "transcript":
            self.transcripts.append(message["text"])
            self._spoken.set()

    async def receive(self) -> dict:
        if self._hangs_up == "after_transcript":
            await self._spoken.wait()
        elif self._hangs_up == "never":
            # A phone that stays on the desk. Without this the client side of
            # the relay's pump always finishes first, so any test about the
            # *provider* side failing would silently be testing a disconnect
            # instead — and would pass for the wrong reason.
            await asyncio.Event().wait()
        else:
            await asyncio.sleep(0)
        return {"type": "websocket.disconnect"}


async def _admitted(db, account, **start):
    """A started session and a ticket that opens its socket."""
    session = await SessionService(db).start(user_id=account.user_id, **start)
    ticket = await VoiceTicketService(db).mint(
        session_id=session.id, user_id=account.user_id
    )
    return session, ticket


async def test_a_socket_reaches_the_panel_and_the_panel_answers(db, funded_account, session_factory, recordings):
    """The whole chain, in one assertion: phone → room → archetype → caption.

    Before this route was rewired, a live socket reached ElevenLabs Agents — one
    remote agent, one voice, a persona configured in somebody else's dashboard —
    and nothing in `app/agents/` was reachable from a phone at all. This is the
    test that says otherwise: the archetype the session was started with is the
    one that composed, and its line came back down the socket as a caption.

    The caption matters independently. `CLAUDE.md` puts live captions in the v1
    accessibility floor, not in a later phase — a voice-only interrogation is
    unusable without them.
    """
    session, ticket = await _admitted(
        db, funded_account, archetypes=["cfo", "champion", "technical_skeptic"]
    )
    model = FakePanelModel(selects="cfo")
    websocket = FakeWebSocket()

    await stream_session(
        websocket,
        session.id,
        ticket,
        VoiceTicketService(db),
        RoomParts(transcriber=FakeTranscriber(), model=model, speaker=None),
        db,
        session_factory,
        recordings,
    )

    assert websocket.accepted
    assert model.wrote_as == ["cfo"]
    assert websocket.transcripts == [LINE]


async def test_a_room_is_grounded_in_its_own_deck(db, ingestion, storage, funded_account, session_factory, recordings):
    """The claims reach the composer, which is the wedge in one assertion.

    `CLAUDE.md` refuses to ship interrogation logic that cannot cite its source,
    and Open Risk #2 says ungrounded generic questions kill retention faster
    than any UI flaw. Everything needed for this existed separately — extraction
    stored the claim, `citable` rendered it, `session_grounding` gathered it —
    and none of it reached a socket until the route built the room.
    """
    from tests.materials import extracted

    material = await extracted(db, ingestion, storage, funded_account)
    session, ticket = await _admitted(
        db, funded_account, archetypes=["cfo"], material_ids=[material.id]
    )
    model = FakePanelModel(selects="cfo")

    await stream_session(
        FakeWebSocket(),
        session.id,
        ticket,
        VoiceTicketService(db),
        RoomParts(transcriber=FakeTranscriber(), model=model, speaker=None),
        db,
        session_factory,
        recordings,
    )

    (context,) = model.composed_with
    assert context.grounding.claims == ("Gross margin of 61% in Q3 2026 (slide 1)",)


async def test_a_deployment_that_cannot_hear_closes_before_metering(db, funded_account, session_factory, recordings):
    """An unconfigured room must not leave a session billing or stranded.

    The session stays out of `active`, which is what keeps the meter off it. A
    room that opened and then failed would hold the user's one-active-session
    lock until the reaper swept — so they could not start another interrogation
    either, over a misconfiguration on our side.
    """
    session, ticket = await _admitted(db, funded_account)
    websocket = FakeWebSocket(hangs_up="immediately")

    await stream_session(
        websocket,
        session.id,
        ticket,
        VoiceTicketService(db),
        RoomParts(transcriber=None, model=FakePanelModel(selects="cfo"), speaker=None),
        db,
        session_factory,
        recordings,
    )

    assert websocket.closed_with == CLOSE_PROVIDER_UNAVAILABLE
    await db.refresh(session)
    assert session.state is not SessionState.ACTIVE


async def test_a_phone_that_hangs_up_mid_write_still_settles_the_room(db, funded_account, session_factory, recordings):
    """The room ends properly even when the user leaves at the worst moment.

    A phone disconnecting finishes one side of the relay's pump, which cancels
    the other — and that other side now writes to the database on every turn.
    Cancelling inside a database call leaves the session unusable, and the very
    next thing to touch it is settlement.

    So the symptom is not a lost telemetry row: it is a room that never settles,
    whose minutes are decided by the reaper instead of by the ending the user
    gave it. The moment somebody is most likely to hang up is right after a
    panelist stops speaking, which is precisely when that write is in flight —
    so this is the ordinary case, not a rare one.

    `FakeWebSocket` hangs up the instant the caption lands, with no sleep, which
    is what a real phone does and what reproduced this in the first place.
    """
    session, ticket = await _admitted(db, funded_account, archetypes=["cfo"])

    await stream_session(
        FakeWebSocket(),
        session.id,
        ticket,
        VoiceTicketService(db),
        RoomParts(
            transcriber=FakeTranscriber(),
            model=FakePanelModel(selects="cfo"),
            speaker=None,
        ),
        db,
        session_factory,
        recordings,
    )

    await db.refresh(session)
    assert session.state is SessionState.SETTLED
    cost = await db.scalar(
        select(SessionCost).where(SessionCost.session_id == session.id)
    )
    assert cost is not None
    assert cost.llm_input_tokens >= 0


async def test_a_dead_panel_model_refunds_instead_of_billing_for_silence(db, funded_account, session_factory, recordings):
    """The failure this whole guard exists for, seen from the socket.

    A composer that stops answering used to leave a room open and metered with
    nobody speaking in it. `CLAUDE.md` is explicit that minutes must never be
    silently over-charged and that a technical failure refunds automatically —
    and neither could happen, because as far as the session was concerned
    nothing had gone wrong.

    Asserted at the route rather than the channel because the refund is the
    point. The channel raising is only a means to it.
    """

    class BrokenModel(FakePanelModel):
        async def compose(self, *, archetype, context, finding=None, dispute=None) -> ModelReply:
            raise ProviderUnavailable(reason="panel_model_error")

    session, ticket = await _admitted(db, funded_account, archetypes=["cfo"])
    websocket = FakeWebSocket(hangs_up="never")

    await stream_session(
        websocket,
        session.id,
        ticket,
        VoiceTicketService(db),
        RoomParts(
            transcriber=FakeTranscriber(),
            model=BrokenModel(selects="cfo"),
            speaker=None,
        ),
        db,
        session_factory,
        recordings,
    )

    assert websocket.closed_with == CLOSE_PROVIDER_UNAVAILABLE
    await db.refresh(session)
    assert session.end_reason is EndReason.PROVIDER_FAILURE


async def test_a_phone_already_gone_is_not_an_error_to_close_on(db, funded_account, session_factory, recordings):
    """Hanging up is how rooms end, and it must not surface as a crash.

    The last thing this route does is close the socket. When the phone has
    already dropped — which is what *caused* the room to end in the ordinary
    case — that close raises `WebSocketDisconnect`, and with nothing catching it
    the room finishes in an unhandled ASGI traceback. Everything that matters is
    already correct by then: the session settled as `client_disconnect`, the
    minutes are right, the cost row is written. Only the log is wrong.

    Worth fixing rather than tolerating. A traceback printed on every normal
    ending is a traceback nobody reads, and the next real one arrives in the
    middle of a hundred of these.
    """

    class Vanished(FakeWebSocket):
        async def close(self, code: int = 1000) -> None:
            await super().close(code)
            raise WebSocketDisconnect(code=1006)

    session, ticket = await _admitted(db, funded_account, archetypes=["cfo"])

    await stream_session(
        Vanished(),
        session.id,
        ticket,
        VoiceTicketService(db),
        RoomParts(
            transcriber=FakeTranscriber(),
            model=FakePanelModel(selects="cfo"),
            speaker=None,
        ),
        db,
        session_factory,
        recordings,
    )

    await db.refresh(session)
    assert session.state is SessionState.SETTLED


async def test_a_room_leaves_its_words_behind(db, funded_account, session_factory, recordings):
    """The whole chain again, but for what survives the socket closing.

    Route → `build_room` → provider → channel → store → a row. Every piece was
    tested on its own and the wiring is the part that is easy to get wrong: a
    room whose store was never constructed still interrogates, still captions
    and still settles, and nothing about it looks broken until the debrief has
    nothing to read.

    Both sides asserted, because they arrive by different routes — the user's
    line from the transcription listener, the panelist's from the turn — and a
    regression is far more likely to lose one than both.
    """
    session, ticket = await _admitted(db, funded_account, archetypes=["cfo"])

    await stream_session(
        FakeWebSocket(),
        session.id,
        ticket,
        VoiceTicketService(db),
        RoomParts(
            transcriber=FakeTranscriber("Our gross margin is sixty-one percent."),
            model=FakePanelModel(selects="cfo"),
            speaker=None,
        ),
        db,
        session_factory,
        recordings,
    )

    kept = await SessionTranscript(session_factory, session_id=session.id).lines()

    # Speaker and text, not the whole `Said`. What this proves is that both
    # sides reach the store through their two different routes; the fields a
    # line carries about *how* it came to be said are asserted where they are
    # decided, in test_orchestrated_channel.py.
    assert [(line.speaker, line.text) for line in kept] == [
        (USER, "Our gross margin is sixty-one percent."),
        ("cfo", LINE),
    ]
