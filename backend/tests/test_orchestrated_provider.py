"""Opening a room we run ourselves.

The sibling of the vendor agent adapter, and the asymmetry between them is the whole
design. ElevenLabs needs no arguments to `open()` — which agent, what persona,
what voice all live on their dashboard. Ours needs to know which archetypes are
seated and which deck to attack, and both are facts in our own database.

Resolved by construction rather than by widening `VoiceProvider.open()`, so the
shared seam is untouched and the vendor adapter never grew a parameter it
cannot use. It is the same call `CLAUDE.md` makes for audit actors: context bound
when the service is built, never passed per call, so nothing downstream can
attribute half a room to a different one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.agents.archetypes import DEFAULT_PANEL, by_name
from app.agents.context import Grounding
from app.agents.model import ModelReply
from app.modules.voice.orchestrated import OrchestratedProvider
from app.modules.voice.transcription import Transcription

pytestmark = pytest.mark.asyncio


class RecordingTranscriber:
    """A transcriber that records whether its stream was ever closed."""

    def __init__(self, results=()) -> None:
        self.results_to_give = list(results)
        self.opened = 0
        self.closed = 0

    def open(self):
        return _Stream(self)


class _Stream:
    def __init__(self, transcriber: RecordingTranscriber) -> None:
        self._transcriber = transcriber

    async def __aenter__(self):
        self._transcriber.opened += 1
        return self

    async def __aexit__(self, *exc) -> bool:
        self._transcriber.closed += 1
        return False

    async def send_audio(self, pcm: bytes) -> None:
        pass

    async def results(self) -> AsyncIterator[Transcription]:
        for result in self._transcriber.results_to_give:
            yield result


class SilentModel:
    """Records the room it was shown, and picks whoever it was told to."""

    def __init__(self, *, speaker: str = "cfo") -> None:
        self._speaker = speaker
        self.spoke_as: list[str] = []
        self.saw_claims: list[tuple[str, ...]] = []

    async def select(self, *, candidates, context) -> ModelReply:
        return ModelReply(text=self._speaker)

    async def compose(self, *, archetype, context, finding=None) -> ModelReply:
        self.spoke_as.append(archetype.name)
        self.saw_claims.append(context.grounding.claims)
        return ModelReply(text="Where is that from?")


async def test_the_room_is_the_one_the_provider_was_built_for():
    """The panel and the deck arrive from construction, not from the wire.

    A client cannot name its own panel at connect time, and that is the point of
    binding it here: the seats were fixed when the session started and checked
    against the caller's tier, so a socket that could re-choose them would let a
    free account open a five-person room by asking twice.

    Asserted by running a turn rather than by reading the channel's attributes —
    which panel is *in* the object is not the claim, and a test that reads it
    would keep passing if the channel stopped using it.
    """
    model = SilentModel(speaker="risk_officer")
    provider = OrchestratedProvider(
        panel=(by_name("risk_officer"), by_name("champion")),
        transcriber=RecordingTranscriber(
            [Transcription(text="We hold their data.", final=True)]
        ),
        model=model,
        grounding=Grounding(claims=("Gross margin of 61% (slide 4)",)),
    )

    async with provider.open() as channel:
        [event async for event in channel.events()]

    assert model.spoke_as == ["risk_officer"]
    assert model.saw_claims == [("Gross margin of 61% (slide 4)",)]


async def test_the_transcription_stream_is_closed_when_the_room_is():
    """A stream left open is a room still running on somebody's invoice.

    The reason `VoiceProvider.open` is a context manager at all. This must not
    depend on the relay tidying up along every path out, and the paths that
    matter are the failing ones — nobody forgets the happy one.
    """
    transcriber = RecordingTranscriber()
    provider = OrchestratedProvider(
        panel=DEFAULT_PANEL, transcriber=transcriber, model=SilentModel()
    )

    async with provider.open():
        assert transcriber.opened == 1

    assert transcriber.closed == 1


async def test_a_room_that_raises_still_closes_its_stream():
    """The path that actually leaks, if anything does."""
    transcriber = RecordingTranscriber()
    provider = OrchestratedProvider(
        panel=DEFAULT_PANEL, transcriber=transcriber, model=SilentModel()
    )

    with pytest.raises(RuntimeError):
        async with provider.open():
            raise RuntimeError("the socket died")

    assert transcriber.closed == 1
