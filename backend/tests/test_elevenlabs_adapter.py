"""Translating one vendor's wire protocol into our event vocabulary.

This is the file that makes the provider interface real rather than decorative.
Everything ElevenLabs-shaped stops here: `conversation_initiation_metadata`,
`vad_score_event`, `audio_base_64` appear in this module and its tests and
nowhere else in the codebase. A second provider is a sibling of this file, not
an edit to the relay.

Pure translation, deliberately separated from the socket that carries it. The
transport cannot be tested without a network and an account; the interpretation
is where the bugs that matter live, and it can be tested exhaustively without
either.
"""

from __future__ import annotations

import base64
import json
from contextlib import asynccontextmanager

import pytest
from websockets.exceptions import ConnectionClosedError

from app.core.errors import ProviderUnavailable
from app.modules.voice.events import (
    AgentAudio,
    ChannelReady,
    Heartbeat,
    Interrupted,
    UserSpoke,
)
from app.modules.voice.providers.elevenlabs import (
    AUDIO_FORMAT,
    SPEECH_THRESHOLD,
    ElevenLabsChannel,
    ElevenLabsProvider,
    to_event,
)


def test_conversation_metadata_is_the_channel_coming_up():
    """Their handshake reply is what activates the session.

    The first message on a healthy conversation, and the only signal that agent
    spin-up succeeded. Everything before it is `provisioning`, which bills
    nothing.
    """
    event = to_event(
        {
            "type": "conversation_initiation_metadata",
            "conversation_initiation_metadata_event": {
                "conversation_id": "conv_123",
                "agent_output_audio_format": "pcm_16000",
                "user_input_audio_format": "pcm_16000",
            },
        }
    )

    assert isinstance(event, ChannelReady)


def test_an_agent_configured_for_the_wrong_format_is_refused_at_the_handshake():
    """A misconfigured agent must fail loudly, at connect, before any audio.

    We cannot dictate the format — it is an agent-level setting, not an
    overridable field, and sending an override that has not been enabled in
    their security settings throws. So the metadata they report is checked
    instead, at the one moment it is knowable.

    Refusing here turns the worst failure mode this integration has into an
    ordinary one. Streaming 24 kHz audio to a client expecting 16 kHz produces
    noise, not an error: it would pass a smoke test, survive a demo, and be
    indistinguishable from a bad microphone in the one room that mattered.
    """
    with pytest.raises(ProviderUnavailable):
        to_event(
            {
                "type": "conversation_initiation_metadata",
                "conversation_initiation_metadata_event": {
                    "conversation_id": "conv_123",
                    "agent_output_audio_format": "pcm_24000",
                    "user_input_audio_format": AUDIO_FORMAT,
                },
            }
        )


def test_agent_audio_arrives_decoded():
    """Base64 is their wire requirement, not a fact about the audio.

    Decoding here is what lets the relay hand raw PCM straight to the phone.
    Leaving it encoded would push a vendor's transport detail all the way to
    the client and make the socket protocol depend on which provider we happen
    to be using.
    """
    pcm = b"\x00\x01\x02\x03"
    event = to_event(
        {
            "type": "audio",
            "audio_event": {
                "audio_base_64": base64.b64encode(pcm).decode(),
                "event_id": 7,
            },
        }
    )

    assert event == AgentAudio(pcm)


def test_a_confident_vad_score_is_the_user_speaking():
    """Their detector reports a probability; the threshold is our policy.

    Kept on this side of the boundary because it is a product decision, not a
    vendor one: it decides when the idle clock resets, and therefore when a
    quiet user gets thrown out of a room they are still thinking in. A second
    provider reports its own confidence and inherits the same judgement.
    """
    event = to_event(
        {"type": "vad_score", "vad_score_event": {"vad_score": SPEECH_THRESHOLD + 0.1}}
    )

    assert isinstance(event, UserSpoke)


def test_background_noise_is_not_speech():
    """The other side of the same decision, and the expensive one to get wrong.

    A threshold low enough to catch room tone would keep an abandoned session
    looking alive indefinitely — the panel talking to nobody while the meter
    runs, which is precisely the failure the idle timeout exists to catch.
    """
    assert (
        to_event(
            {
                "type": "vad_score",
                "vad_score_event": {"vad_score": SPEECH_THRESHOLD - 0.1},
            }
        )
        is None
    )


def test_an_interruption_is_a_barge_in():
    event = to_event({"type": "interruption", "interruption_event": {"event_id": 9}})

    assert isinstance(event, Interrupted)


def test_a_ping_is_the_channel_proving_it_is_alive():
    """Their keepalive doubles as our heartbeat.

    One mechanism rather than two: the connection is either delivering or it is
    not, and inventing a second liveness signal alongside theirs would give the
    reaper two answers that can disagree.
    """
    event = to_event(
        {"type": "ping", "ping_event": {"event_id": 3, "ping_ms": 50}}
    )

    assert isinstance(event, Heartbeat)


def test_a_message_we_do_not_act_on_is_ignored_rather_than_refused():
    """Forward compatibility, and not a hypothetical one.

    ElevenLabs ships new client events regularly — `agent_tool_request`,
    `mcp_connection_status`, `guardrail_triggered` and others already exist
    that this relay has no opinion about. An adapter that raised on anything
    unrecognised would turn any feature release of theirs into an outage of
    ours, mid-session, on a live room.
    """
    assert to_event({"type": "agent_response_correction", "whatever": {}}) is None
    assert to_event({"type": "a_type_that_does_not_exist_yet"}) is None


# --- Transport ------------------------------------------------------------
#
# The socket itself is faked: it is a network, which `mocking.md` names as a
# boundary. What is real below is everything we decide — what we put on the
# wire, what we answer, and what a dropped connection turns into.


class FakeSocket:
    """A websocket that replays scripted frames and records what we sent."""

    def __init__(self, incoming: list[str] | None = None) -> None:
        self.incoming = incoming or []
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def __aiter__(self):
        for frame in self.incoming:
            yield frame


async def test_a_ping_is_answered_so_the_connection_survives():
    """Their keepalive expects a reply, and an unanswered one drops the room.

    This is transport rather than translation — the relay upstream has no idea
    a pong exists, and should not. It is asserted because forgetting it does
    not fail here: it fails minutes later, as a live session dying for no
    visible reason.
    """
    socket = FakeSocket(['{"type": "ping", "ping_event": {"event_id": 42}}'])
    channel = ElevenLabsChannel(socket)

    events = [event async for event in channel.events()]

    assert [isinstance(event, Heartbeat) for event in events] == [True]
    assert json.loads(socket.sent[0]) == {"type": "pong", "event_id": 42}


async def test_user_audio_goes_out_base64_encoded():
    """Base64 is applied here and only here.

    Their protocol requires it; ours does not, which is why the leg from the
    phone carries raw binary frames. Paying the 33% on both legs would be
    bandwidth spent to satisfy a requirement that only exists on one of them.
    """
    socket = FakeSocket()
    pcm = b"\x10\x11\x12\x13"

    await ElevenLabsChannel(socket).send_audio(pcm)

    assert json.loads(socket.sent[0]) == {
        "user_audio_chunk": base64.b64encode(pcm).decode()
    }


async def test_a_dropped_connection_never_names_the_vendor():
    """CLAUDE.md: provider failures surface as ProviderUnavailable, unnamed.

    Naming it exposes internal architecture to whoever is probing, and goes
    stale the moment the voice provider is swapped — which this whole module
    exists to keep cheap. The relay upstream already knows how to end a room on
    this exception; what it must not be handed is a vendor's own error type.
    """
    socket = FakeSocket()

    async def dies(self):
        raise ConnectionClosedError(None, None)
        yield  # pragma: no cover

    socket.__class__.__aiter__ = dies
    channel = ElevenLabsChannel(socket)

    with pytest.raises(ProviderUnavailable):
        [event async for event in channel.events()]


async def test_a_provider_that_cannot_be_reached_never_names_the_vendor():
    """Dial failures are the same story as dropped ones, at a different moment.

    DNS failure, refused connection, TLS error — all identical to the relay,
    which cares only that the room never opened. What matters here is that none
    of them reach the caller wearing a vendor's exception type.
    """

    @asynccontextmanager
    async def refuses(url, **kwargs):
        raise OSError("no route to host")
        yield  # pragma: no cover

    provider = ElevenLabsProvider(
        api_key="k", agent_id="a", connect=refuses
    )

    with pytest.raises(ProviderUnavailable):
        async with provider.open():
            pass  # pragma: no cover


async def test_dialling_addresses_the_configured_agent_and_authenticates():
    """What the dial actually has to get right, now that it pins nothing.

    The handshake carries no config override. Audio format is set on the agent
    and verified from the metadata it reports back, because an override that
    has not been enabled in their security settings throws — a handshake that
    tried to pin the format would fail every connection instead of protecting
    any of them.
    """
    socket = FakeSocket()

    @asynccontextmanager
    async def connects(url, **kwargs):
        connects.url = url
        connects.headers = kwargs.get("additional_headers")
        yield socket

    provider = ElevenLabsProvider(
        api_key="secret-key", agent_id="agent-42", connect=connects
    )
    async with provider.open():
        pass

    assert "agent_id=agent-42" in connects.url
    assert connects.headers == {"xi-api-key": "secret-key"}
    assert json.loads(socket.sent[0]) == {
        "type": "conversation_initiation_client_data"
    }
