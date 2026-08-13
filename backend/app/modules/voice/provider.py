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


class VoiceProvider(Protocol):
    """Opens channels. One instance per process, not per session."""

    def open(self) -> AbstractAsyncContextManager[VoiceChannel]:
        """Dial the provider.

        A context manager because a channel that is not closed is a room still
        running on the provider's invoice — which must not depend on the relay
        remembering to tidy up on every path out, including the failing ones.
        """
        ...
