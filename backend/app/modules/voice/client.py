"""The phone, as the relay sees it.

Wraps a Starlette `WebSocket` in our `ClientChannel` protocol. Everything
framework-shaped stops here, so the relay is testable without a network and
would not notice if the transport changed underneath it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import WebSocket, WebSocketDisconnect

from app.core.logging import get_logger

log = get_logger(__name__, tag="voice")

#: Sent as a text frame, so it cannot be mistaken for audio. Binary frames on
#: this socket are always PCM16 samples in both directions — keeping control
#: messages on a different frame type means the client never has to inspect a
#: payload to know what it is holding.
DISCARD_PLAYBACK = {"type": "discard_playback"}


class WebSocketClientChannel:
    """One connected client."""

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket

    async def send_audio(self, pcm: bytes) -> None:
        """Raw samples, as a binary frame.

        No base64 on this leg. Their protocol requires it; ours does not, and
        paying the 33% expansion in both directions would be bandwidth spent on
        a requirement that exists at the other end of the relay.
        """
        await self._websocket.send_bytes(pcm)

    async def discard_playback(self) -> None:
        """Barge-in: drop what the device has buffered and not yet played."""
        await self._websocket.send_json(DISCARD_PLAYBACK)

    async def audio(self) -> AsyncIterator[bytes]:
        """What the user is saying, until the connection ends.

        Returning — rather than raising — on disconnect is what tells the relay
        the *client* ended the conversation, which is what makes the difference
        between settling as `client_disconnect` and settling as a provider
        failure. One refunds and the other does not.

        Text frames are ignored rather than refused. The client has no control
        messages to send today, and a future one must not be able to kill a
        live room by arriving before this end knows what it means.
        """
        try:
            while True:
                message = await self._websocket.receive()

                if message["type"] == "websocket.disconnect":
                    return
                if (pcm := message.get("bytes")) is not None:
                    yield pcm
        except WebSocketDisconnect:
            return
