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
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.database import get_db
from app.core.errors import FlintroomError, NotAuthenticated, ProviderUnavailable
from app.core.logging import get_logger
from app.core.request_context import current_request_id
from app.modules.voice.client import WebSocketClientChannel
from app.modules.voice.dependencies import RoomPartsDep, VoiceTicketServiceDep
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
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return

    await websocket.accept()
    log.info("stream_opened", user_id=str(user_id), session_id=str(session_id))

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
        )
    except ProviderUnavailable:
        # Nothing has been metered — the room never opened. Closed here rather
        # than through the relay, which has no session to settle yet.
        await websocket.close(code=CLOSE_PROVIDER_UNAVAILABLE)
        return

    relay = VoiceRelay(
        db,
        provider=room,
        client=WebSocketClientChannel(websocket),
        actor=ActorContext.user(user_id, request_id=current_request_id()),
    )

    try:
        await relay.run(session_id=session_id)
    except ProviderUnavailable:
        # The relay has already ended the room and refunded whatever was owed.
        # The client is told only that the room is over, never by whom.
        await websocket.close(code=CLOSE_PROVIDER_UNAVAILABLE)
        return
    except WebSocketDisconnect:
        # The user closed the app. The relay settles this as a client
        # disconnect; nothing here is left to do but stop.
        log.info("stream_disconnected", session_id=str(session_id))
        return
    except FlintroomError as exc:
        log.warning("stream_refused", session_id=str(session_id), code=exc.code)
        await websocket.close(code=CLOSE_PROVIDER_UNAVAILABLE)
        return

    await websocket.close()
