"""Fakes for the system boundaries — the vendor, and the client socket.

`mocking.md` allows exactly these: external APIs and things we do not control.
The database, the ledger and the session service are real in every test that
uses these, because a relay proved correct against a fake session service has
proved only that two fakes agree.

Scripted rather than clever: a test hands over the exact events it wants the
provider to emit, in order. That makes an ordering bug reproducible, which is
the property that matters most for a stream.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from app.core.errors import ProviderUnavailable
from app.modules.voice.events import VoiceEvent


class FakeVoiceChannel:
    """A channel that says what it was told to say, and remembers what it heard.

    `keep_open` decides what happens after the script runs out. Ending is the
    convenience most tests want — it is what lets `run` return so they can
    assert. Staying open is the realistic one, and it is required by any test
    about *which* side of the conversation finished first: with both sides free
    to end, the winner is a race and the assertion is a coin toss.
    """

    def __init__(
        self, events: Sequence[VoiceEvent], *, keep_open: bool = False
    ) -> None:
        self._events = events
        self._keep_open = keep_open
        self.received: list[bytes] = []

    async def events(self) -> AsyncIterator[VoiceEvent]:
        for event in self._events:
            yield event
        if self._keep_open:
            await asyncio.Event().wait()

    async def send_audio(self, pcm: bytes) -> None:
        self.received.append(pcm)


class FakeVoiceProvider:
    """A provider that opens one scripted channel.

    Keeps a reference to the channel it opened so a test can ask what the relay
    forwarded — the provider side has no other observable effect.
    """

    def __init__(
        self, events: Sequence[VoiceEvent], *, keep_open: bool = False
    ) -> None:
        self._events = events
        self.channel = FakeVoiceChannel(events, keep_open=keep_open)

    @asynccontextmanager
    async def open(self) -> AsyncIterator[FakeVoiceChannel]:
        yield self.channel


class FakeClientChannel:
    """A phone: remembers what it was played, says what it was scripted to say.

    Going quiet is not the same as hanging up. Once the scripted frames run out
    this blocks rather than ending, because a real socket with nobody talking
    into it stays open — and a fake that ended instead would let every test
    pass by finishing the conversation early.
    """

    def __init__(self, inbound: Sequence[bytes] = ()) -> None:
        self.sent: list[bytes] = []
        #: `(speaker, text)`, because one utterance is one caption and the
        #: name is part of it — a fake that kept only the words would let a
        #: relay that dropped the speaker pass.
        self.captions: list[tuple[str, str]] = []
        self.discarded = 0
        self.yielded = 0
        self._inbound = list(inbound)
        self._hung_up = asyncio.Event()

        #: What the room said it was doing, in order (#24).
        self.attended: list[str] = []

        #: How the panel was said to be receiving the argument, in order (#74).
        self.temperatures: list[str] = []
    async def send_audio(self, pcm: bytes) -> None:
        self.sent.append(pcm)

    async def send_transcript(self, text: str, speaker: str) -> None:
        self.captions.append((speaker, text))

    async def attending(self, state: str) -> None:
        self.attended.append(state)

    async def temperature(self, state: str) -> None:
        self.temperatures.append(state)

    async def turn_finished(self) -> None:
        self.yielded += 1

    async def discard_playback(self) -> None:
        self.discarded += 1

    async def audio(self) -> AsyncIterator[bytes]:
        for frame in self._inbound:
            yield frame
        await self._hung_up.wait()

    def hang_up(self) -> None:
        """Model the user closing the app."""
        self._hung_up.set()


class DyingVoiceProvider(FakeVoiceProvider):
    """A provider that comes up, says its piece, and then breaks.

    The failure arrives mid-stream rather than at dial time, which is the
    distinction that matters: by then the room has opened, the meter has been
    running, and the user is owed their minutes back.
    """

    def __init__(self, events: Sequence[VoiceEvent]) -> None:
        super().__init__(events)
        self.channel = _DyingChannel(events)


class _DyingChannel(FakeVoiceChannel):
    async def events(self) -> AsyncIterator[VoiceEvent]:
        for event in self._events:
            yield event
        raise ProviderUnavailable(reason="stream_closed")


class UnavailableVoiceProvider:
    """A provider that cannot be dialled at all.

    Raises what a real adapter raises: the vendor's own exception is caught and
    translated inside that adapter, so nothing above it — including this fake —
    ever refers to a vendor (CLAUDE.md → Logging and error handling).
    """

    @asynccontextmanager
    async def open(self) -> AsyncIterator[FakeVoiceChannel]:
        raise ProviderUnavailable(reason="dial_failed")
        yield  # pragma: no cover — unreachable, but makes this a generator
