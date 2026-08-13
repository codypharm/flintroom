"""The ElevenLabs Agents adapter.

Every vendor-shaped name in the system is contained in this module:
`conversation_initiation_metadata`, `vad_score_event`, `audio_base_64`,
`user_audio_chunk`. Nothing above it knows which provider is on the other end,
which is what makes the Gemini Live fallback in `CLAUDE.md` a sibling file
rather than a rewrite.

Translation is a pure function, separated from the socket that carries it. The
transport needs a network and an account to exercise; the interpretation is
where the bugs live and can be tested exhaustively without either.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import websockets
from websockets.exceptions import WebSocketException

from app.core.errors import ProviderUnavailable
from app.core.logging import get_logger
from app.modules.voice.events import (
    AgentAudio,
    ChannelReady,
    Heartbeat,
    Interrupted,
    UserSpoke,
    VoiceEvent,
)

log = get_logger(__name__, tag="voice")

#: What ElevenLabs must send and expect. PCM throughout, so the relay never
#: transcodes: their agent socket accepts base64 PCM and nothing else, and
#: choosing a compressed format on our own leg would buy uplink bandwidth at
#: the price of a decode in the middle of the latency budget.
AUDIO_FORMAT = "pcm_16000"

#: Above this, we treat their detector's output as the user speaking.
#:
#: Ours to choose, not theirs. It decides when the idle clock resets, so it is
#: the number standing between a user thinking about a hostile question and
#: being thrown out of the room for silence — and, in the other direction,
#: between an abandoned room and one kept alive by its own air conditioning.
#:
#: 0.5 is a starting point, not a measured value. Calibrating it against real
#: rooms belongs to the same spike that measures latency and cost (Product.md
#: §4.3), because all three need the same thing: real audio through a real
#: provider.
SPEECH_THRESHOLD = 0.5


#: Their conversation endpoint. Regional variants exist
#: (`api.eu.residency.elevenlabs.io` and others) and choosing one is a data
#: residency decision rather than a technical one, so it stays configurable.
DEFAULT_ENDPOINT = "wss://api.elevenlabs.io/v1/convai/conversation"


class ElevenLabsProvider:
    """Dials ElevenLabs Agents. One instance per process.

    Built once in the application lifespan, like the auth verifiers, because a
    provider constructed per request would rebuild connection state on every
    room — and this is the object that will eventually hold pooling and
    per-archetype voice configuration.

    `connect` is injected so the dialling path is substitutable. Nothing in the
    test suite exercises the real endpoint: reaching it needs an account, and
    what it would prove is exactly what the §4.3 spike exists to measure.
    """

    def __init__(
        self,
        *,
        api_key: str,
        agent_id: str,
        endpoint: str = DEFAULT_ENDPOINT,
        connect: Any = None,
    ) -> None:
        self._api_key = api_key
        self._agent_id = agent_id
        self._endpoint = endpoint
        self._connect = connect or websockets.connect

    @asynccontextmanager
    async def open(self) -> AsyncIterator[ElevenLabsChannel]:
        """Open a conversation, and make sure it is closed again.

        A context manager because a channel left open is a room still running
        on their invoice, and that must not depend on the relay remembering to
        tidy up on every path out — including the failing ones.

        UNVERIFIED until an API key exists: that `xi-api-key` is accepted on
        the handshake for a private agent. The documented alternative is a
        signed URL fetched from `/v1/convai/conversation/get-signed-url`, which
        exists so browser clients need not hold the key. We are server-side and
        already hold it, so the header is the cheaper path if it works. This is
        the first thing the spike should confirm.
        """
        url = f"{self._endpoint}?agent_id={self._agent_id}"
        try:
            async with self._connect(
                url, additional_headers={"xi-api-key": self._api_key}
            ) as socket:
                # Audio format is deliberately *not* overridden here. It is an
                # agent-level setting rather than an overridable field, and
                # ElevenLabs throws on an override that has not been enabled in
                # the agent's security settings — so sending one would fail
                # every connection rather than pin anything.
                #
                # The format is asserted on the way back instead, from the
                # metadata they report. See `ElevenLabsChannel.events`.
                await socket.send(
                    json.dumps({"type": "conversation_initiation_client_data"})
                )
                yield ElevenLabsChannel(socket)
        except (WebSocketException, OSError) as exc:
            # Includes DNS failures, refused connections and TLS errors, all of
            # which the relay treats identically: the room never opened.
            log.warning("voice_dial_failed", error=type(exc).__name__)
            raise ProviderUnavailable(reason="dial_failed") from exc


class ElevenLabsChannel:
    """One live conversation, over their WebSocket.

    Holds the socket and nothing else. Everything it decides — what goes on the
    wire, what must be answered, what a dropped connection becomes — is here;
    what the messages *mean* is `to_event`.
    """

    def __init__(self, socket: Any) -> None:
        self._socket = socket

    async def send_audio(self, pcm: bytes) -> None:
        """Forward the user's audio. Base64 is applied here and only here.

        Their protocol requires it; ours does not, which is why the leg from
        the phone carries raw binary frames. Paying the 33% expansion on both
        legs would be bandwidth spent to satisfy a requirement that exists on
        one of them.
        """
        await self._socket.send(
            json.dumps({"user_audio_chunk": base64.b64encode(pcm).decode()})
        )

    async def events(self) -> AsyncIterator[VoiceEvent]:
        """Their stream, translated, with the protocol's obligations honoured.

        The pong is sent from here rather than surfaced upstream: answering a
        keepalive is a fact about their transport, and the relay has no reason
        to learn that one exists. Forgetting it would not fail here — it fails
        minutes later, as a live room dying for no visible reason.
        """
        try:
            async for frame in self._socket:
                message = json.loads(frame)
                if message.get("type") == "ping":
                    await self._pong(message)
                if (event := to_event(message)) is not None:
                    yield event
        except WebSocketException as exc:
            # The vendor's exception stops here. CLAUDE.md: provider failures
            # surface unnamed, because naming one exposes internal
            # architecture and goes stale the moment the provider is swapped.
            log.warning("voice_channel_dropped", error=type(exc).__name__)
            raise ProviderUnavailable(reason="channel_dropped") from exc

    async def _pong(self, message: dict[str, Any]) -> None:
        await self._socket.send(
            json.dumps(
                {"type": "pong", "event_id": message["ping_event"]["event_id"]}
            )
        )


def _require_expected_audio_format(metadata: dict[str, Any]) -> None:
    """Refuse an agent configured for audio the phone cannot play.

    The format is theirs to declare, not ours to set: it is configured on the
    agent rather than per conversation, and an override that has not been
    enabled in their security settings throws rather than applies. So this
    checks what they report, at the one moment it becomes knowable.

    Worth a hard failure because the alternative is the quietest bug this
    integration can produce. The relay transcodes nothing, so 24 kHz audio sent
    to a client expecting 16 kHz arrives as noise rather than as an error — it
    would pass a smoke test, survive a demo, and be indistinguishable from a
    bad microphone in the one room that mattered.

    Raised as `ProviderUnavailable`, so the room ends the way every other
    upstream failure does: settled, refunded, and without naming the vendor.
    """
    formats = {
        "agent_output": metadata.get("agent_output_audio_format"),
        "user_input": metadata.get("user_input_audio_format"),
    }
    wrong = {side: got for side, got in formats.items() if got != AUDIO_FORMAT}
    if not wrong:
        return

    log.error("voice_audio_format_mismatch", expected=AUDIO_FORMAT, **wrong)
    raise ProviderUnavailable(reason="audio_format_mismatch", expected=AUDIO_FORMAT)


def to_event(message: dict[str, Any]) -> VoiceEvent | None:
    """Translate one of their messages. `None` means nothing upstream acts on it.

    Unrecognised types are ignored rather than refused. ElevenLabs ships new
    client events regularly — `agent_tool_request`, `guardrail_triggered` and
    `mcp_connection_status` already exist and this relay has no opinion about
    any of them. Raising on the unfamiliar would turn a feature release of
    theirs into an outage of ours, mid-session, on a live room.
    """
    match message.get("type"):
        case "conversation_initiation_metadata":
            # Their handshake reply, and the only evidence that agent spin-up
            # succeeded. Until it arrives the session is `provisioning` and
            # bills nothing.
            _require_expected_audio_format(
                message["conversation_initiation_metadata_event"]
            )
            return ChannelReady()

        case "audio":
            encoded = message["audio_event"]["audio_base_64"]
            # Decoded here so the relay carries raw PCM. Base64 is their
            # transport requirement, not a property of the audio, and leaving
            # it encoded would push a vendor detail all the way to the phone.
            return AgentAudio(base64.b64decode(encoded))

        case "vad_score":
            score = message["vad_score_event"]["vad_score"]
            return UserSpoke() if score >= SPEECH_THRESHOLD else None

        case "interruption":
            return Interrupted()

        case "ping":
            # Their keepalive doubles as our heartbeat rather than us inventing
            # a second liveness signal beside it — two answers to "is this
            # connection alive" are two answers that can disagree, and the
            # reaper acts on one of them.
            return Heartbeat()

    return None
