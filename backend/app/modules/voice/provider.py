"""The seam a voice provider plugs into.

Structural (`Protocol`) rather than inherited, so an adapter is a class that
happens to fit rather than one that had to import us — which is what keeps a
vendor SDK wrapper from acquiring a dependency on our module graph.

The contract is deliberately small: open a channel, read events off it, and be
closed when the caller is done. Anything a specific vendor also offers stays
inside that vendor's adapter.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from app.modules.voice.events import VoiceEvent


class VoiceChannel(Protocol):
    """One live conversation with a provider."""

    def events(self) -> AsyncIterator[VoiceEvent]:
        """Everything the provider has to say, in our vocabulary."""
        ...

    async def send_audio(self, pcm: bytes) -> None:
        """Forward what the user said. PCM16, 16 kHz mono.

        Whatever encoding the vendor's wire format demands — ElevenLabs wants
        base64 — is applied inside the adapter. The relay hands over samples.
        """
        ...


class ClientChannel(Protocol):
    """The socket to the phone — the relay's other side.

    A protocol rather than a `WebSocket` for the same reason the provider is
    one: the relay's behaviour is worth testing without a network, and the
    route stays free to hand in whatever the framework gave it.
    """

    async def send_audio(self, pcm: bytes) -> None:
        """Play this on the user's device. PCM16, 16 kHz mono, as received."""
        ...

    async def send_transcript(self, text: str) -> None:
        """Show this as the panel's current line.

        A separate method from `send_audio` rather than a flag on it, because
        the two are different obligations at the far end: one is played and one
        is displayed, and the phone should never have to inspect a payload to
        learn which it is holding.
        """
        ...

    async def discard_playback(self) -> None:
        """Drop whatever is buffered and unplayed.

        Called on barge-in. Audio runs ahead of playback, so a panelist the
        user has already cut across still has frames queued on the device —
        and letting those finish is the room failing to be interruptible.
        """
        ...

    def audio(self) -> AsyncIterator[bytes]:
        """What the user is saying, frame by frame, until they hang up.

        Ends only when the connection does. Silence is not the end of this
        iterator — a user thinking about a hostile question is still in the
        room, and the idle timeout is what decides otherwise.
        """
        ...


class VoiceProvider(Protocol):
    """Opens channels. One instance per process, not per session."""

    def open(self) -> AbstractAsyncContextManager[VoiceChannel]:
        """Dial the provider.

        A context manager because a channel that is not closed is a room still
        running on the provider's invoice — which must not depend on the relay
        remembering to tidy up on every path out, including the failing ones.
        """
        ...
