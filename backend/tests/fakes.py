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

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from app.core.errors import ProviderUnavailable
from app.modules.voice.events import VoiceEvent


class FakeVoiceChannel:
    """A channel that says what it was told to say, then ends."""

    def __init__(self, events: Sequence[VoiceEvent]) -> None:
        self._events = events

    async def events(self) -> AsyncIterator[VoiceEvent]:
        for event in self._events:
            yield event


class FakeVoiceProvider:
    """A provider that opens one scripted channel."""

    def __init__(self, events: Sequence[VoiceEvent]) -> None:
        self._events = events

    @asynccontextmanager
    async def open(self) -> AsyncIterator[FakeVoiceChannel]:
        yield FakeVoiceChannel(self._events)


class DyingVoiceProvider:
    """A provider that comes up, says its piece, and then breaks.

    The failure arrives mid-stream rather than at dial time, which is the
    distinction that matters: by then the room has opened, the meter has been
    running, and the user is owed their minutes back.
    """

    def __init__(self, events: Sequence[VoiceEvent]) -> None:
        self._events = events

    @asynccontextmanager
    async def open(self) -> AsyncIterator[FakeVoiceChannel]:
        yield _DyingChannel(self._events)


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
