"""The stream socket.

Thin, like every other router here: authenticate, hand off to the relay, close.
No business logic and no database work — what a room does while it is open is
`VoiceRelay`'s, and this exists to connect one to a socket.

The protocol on this socket is deliberately not OpenAPI-shaped, because OpenAPI
does not describe WebSockets. Binary frames are PCM16 at 16 kHz mono in both
directions; text frames are control messages from us to the client. See
`docs/voice-stream-protocol.md`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.actors import ActorContext
from app.core.database import get_db, get_session_factory
from app.core.errors import FlintroomError, NotAuthenticated, ProviderUnavailable
from app.core.logging import get_logger
from app.core.request_context import current_request_id
from app.modules.sessions.preferences import PreferenceService
from app.modules.voice.client import WebSocketClientChannel
from app.modules.voice.dependencies import (
    RoomPartsDep,
    RoomRecordingsDep,
    VoiceTicketServiceDep,
)
from app.modules.voice.mixing import RoomMixer
from app.modules.voice.relay import VoiceRelay
from app.modules.voice.room import build_room

log = get_logger(__name__, tag="voice")

router = APIRouter(tags=["voice"])

#: Close codes in the 4000–4999 range are the application's to define.
#: Deliberately few: the client's response to every one of them is the same —
#: stop streaming and go to the debrief — and a richer taxonomy would mostly
#: tell whoever is probing which guard they tripped.
CLOSE_UNAUTHORIZED = 4401
CLOSE_PROVIDER_UNAVAILABLE = 4502


@router.websocket("/sessions/{session_id}/stream")
async def stream_session(
    websocket: WebSocket,
    session_id: uuid.UUID,
    ticket: str,
    tickets: VoiceTicketServiceDep,
    parts: RoomPartsDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    session_factory: Annotated[
        async_sessionmaker[AsyncSession], Depends(get_session_factory)
    ],
    recordings: RoomRecordingsDep,
) -> None:
    """Carry one interrogation between the phone and the voice provider.

    The ticket is redeemed *before* the socket is accepted, so an unauthorised
    caller never reaches an open connection. Redeeming is also how this learns
    who the caller is: there is no header to read on a handshake a browser can
    make, which is why the ticket carries the identity rather than just the
    permission.
    """
    try:
        user_id = await tickets.redeem(ticket=ticket, session_id=session_id)
    except NotAuthenticated:
        # Closed without accepting. The refusal says nothing about whether the
        # session exists, matching the not-found-not-forbidden rule the HTTP
        # routes follow — a socket that answered differently for a real id
        # would be an enumeration oracle the REST layer deliberately is not.
        await _close(websocket, CLOSE_UNAUTHORIZED)
        return

    await websocket.accept()
    log.info("stream_opened", user_id=str(user_id), session_id=str(session_id))

    # Read once, here, before a single frame is accumulated. A room started by
    # somebody who turned recording off never holds their audio in memory at all
    # — "off" should mean not gathered, not merely not kept.
    records = await PreferenceService(db).records_rooms(user_id=user_id)

    # **One object, two readers, and #69 is why it is built here.** The mixer is
    # the room's recording *and* its clock: the relay accumulates into it, and
    # the channel reads `elapsed()` to stamp each transcript line with where in
    # that recording it began. Two mixers would be two timelines, and the
    # offsets would be positions in a file nobody was writing.
    #
    # This is the only place that can build it. `build_room` runs before the
    # relay exists, and the relay is constructed from what `build_room` returns
    # — so neither can hand one to the other, and the router is what sees both.
    #
    # `keeping` is the preference, not a second gate. The clock runs either way;
    # what the preference decides is whether any samples are stored.
    #
    # `resumed` is the segment a dropped connection already stored, when there
    # is one — docs/reconnect.md. Seeding the mixer with it is what makes the
    # final save hold the whole room and keeps every pre-drop transcript
    # offset anchored to a moment the file actually contains. A fresh room
    # pays one storage miss for this, which is the cheapest honest way to ask
    # "was there a segment" without a second query inventing the answer.
    resumed = (
        await recordings.saved_pcm(session_id=session_id)
        if records and recordings is not None
        else b""
    )
    mixer = RoomMixer(keeping=records, resumed=resumed)

    try:
        # After the ticket, because the room needs to know whose it is: seats
        # and claims are per session, and the claims query is filtered by owner.
        # There is no header to read on a socket handshake, so redemption is
        # the only thing that establishes identity — which is why this cannot
        # be a dependency the way the process-wide parts are.
        room = await build_room(
            db,
            session_id=session_id,
            user_id=user_id,
            transcriber=parts.transcriber,
            model=parts.model,
            speaker=parts.speaker,
            opener_speaker=parts.opener_speaker,
            reader=parts.reader,
            # The factory, not `db`. The room's transcript is written from a task
            # running beside the relay's loop, and one `AsyncSession` cannot be
            # flushed from two at once — see `SessionTranscript`.
            session_factory=session_factory,
            # Read-only from this side: the room asks what time it is and
            # never advances it. See `RoomClock`.
            clock=mixer,
        )
    except ProviderUnavailable:
        # Nothing has been metered — the room never opened. Closed here rather
        # than through the relay, which has no session to settle yet.
        await _close(websocket, CLOSE_PROVIDER_UNAVAILABLE)
        return

    relay = VoiceRelay(
        db,
        provider=room,
        client=WebSocketClientChannel(websocket),
        actor=ActorContext.user(user_id, request_id=current_request_id()),
        recordings=recordings,
        records=records,
        # The same object the room above is reading its clock from.
        mixer=mixer,
    )

    try:
        await relay.run(session_id=session_id)
    except ProviderUnavailable:
        # The relay has already ended the room and refunded whatever was owed.
        # The client is told only that the room is over, never by whom.
        await _close(websocket, CLOSE_PROVIDER_UNAVAILABLE)
        return
    except WebSocketDisconnect:
        # The user closed the app. The relay settles this as a client
        # disconnect; nothing here is left to do but stop.
        log.info("stream_disconnected", session_id=str(session_id))
        return
    except FlintroomError as exc:
        log.warning("stream_refused", session_id=str(session_id), code=exc.code)
        await _close(websocket, CLOSE_PROVIDER_UNAVAILABLE)
        return

    await _close(websocket)


async def _close(websocket: WebSocket, code: int = 1000) -> None:
    """Close, unless the phone has already gone.

    Hanging up is the ordinary way a room ends, and by the time the relay has
    settled it the socket is frequently already dead — so closing it raises,
    and an unhandled raise turns every normal ending into an ASGI traceback.
    Nothing is wrong when that happens: the session is settled, the minutes are
    right, the cost row is written. Only the log is.

    Worth suppressing rather than tolerating. A traceback printed on every
    ordinary ending is one nobody reads, and the next real one arrives buried in
    a hundred of these.
    """
    try:
        await websocket.close(code=code)
    except (WebSocketDisconnect, RuntimeError):
        # RuntimeError is Starlette's answer to closing a socket it has already
        # completed; both mean the same thing here and neither is ours to act on.
        log.debug("stream_already_closed")
