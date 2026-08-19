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

#: Carries a payload, unlike `discard_playback`, which is why it is a type name
#: rather than a whole message: the text is filled in per utterance.
TRANSCRIPT = "transcript"

#: The panel's turn is over and the presenter has the floor. Whole message,
#: like `discard_playback`: there is nothing to fill in, and the room strictly
#: alternates, so naming who yielded would repeat the caption that just went.
TURN_FINISHED = {"type": "turn_finished"}


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

    async def send_transcript(self, text: str, speaker: str) -> None:
        """The panel's current line and who said it, for the caption field.

        Deliberately not logged, at any level. `CLAUDE.md` forbids transcript
        text in logs, and unlike a credential it cannot be caught by key-name
        redaction — the only thing that keeps it out is nobody passing it. The
        speaker is only an archetype name and carries nothing about the user,
        but it travels inside the same call and there is no line here to put it
        on.

        One message rather than two. The live screen has to develop the right
        tray at the moment the words appear, and a name arriving on its own
        frame would be a synchronisation problem invented for nothing.
        """
        await self._websocket.send_json(
            {"type": TRANSCRIPT, "text": text, "speaker": speaker}
        )

    async def turn_finished(self) -> None:
        """The panel is done, and the floor is the presenter's again.

        A whole message rather than a type name, like `discard_playback` and
        unlike `transcript`: there is nothing to fill in. The fact is the
        message.
        """
        await self._websocket.send_json(TURN_FINISHED)

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
