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
from app.agents.context import USER, Grounding, Said
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

    async def compose(self, *, archetype, context, finding=None, dispute=None) -> ModelReply:
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


async def test_each_room_gets_its_own_running_claim_set():
    """A shared Auditor would carry one person's figures into somebody else's room.

    The Auditor accumulates every figure spoken during a session and checks each
    new one against it. Built once and reused, the second room would open
    holding the first user's numbers — and would then accuse its user of
    contradicting a claim they never made, quoting a moment from a session that
    was not theirs.

    That is a correctness failure and a privacy one at the same time: the
    summary a panelist reads aloud carries the earlier figure verbatim. It is
    also exactly the shape `CLAUDE.md` guards against elsewhere by binding
    per-session context at construction — and this is the one thing in the
    room that is per *stream* rather than per session, since a provider outlives
    a dropped socket and can be opened again.
    """
    reader = object()
    provider = OrchestratedProvider(
        panel=DEFAULT_PANEL,
        transcriber=RecordingTranscriber(),
        model=SilentModel(),
        grounding=Grounding(),
        reader=reader,
    )

    async with provider.open() as first:
        first_auditor = first._auditor
        first_auditor.heard.append(object())

    async with provider.open() as second:
        assert second._auditor is not first_auditor
        assert second._auditor.heard == [], "a second room opened holding the first's figures"


async def test_a_deployment_with_no_claim_reader_still_opens_rooms():
    """One unconfigured model must not take the interrogation with it.

    The same trade as the speaker: auth, balances, transcription, routing,
    composition and captions all work without a claim reader. What is lost is
    the panel noticing a figure that moved — a kind of question, not a session.
    """
    provider = OrchestratedProvider(
        panel=DEFAULT_PANEL,
        transcriber=RecordingTranscriber(),
        model=SilentModel(),
        grounding=Grounding(),
    )

    async with provider.open() as channel:
        assert channel._auditor is None


async def test_a_room_files_its_words_where_they_will_outlive_it():
    """The provider carries the store down to the channel that does the writing.

    `build_room` is the only place that knows which session a room belongs to,
    so the store is bound there and travels with the provider — the same
    asymmetry that made `OrchestratedProvider` per-room rather than per-process.
    A provider that accepted one and dropped it would leave every room silently
    unrecorded, and nothing about a live interrogation would look wrong.

    Asserted by running a turn rather than by reading the channel's attributes,
    for the reason the panel test gives: what is *in* the object is not the
    claim.
    """
    kept: list[Said] = []

    class Keeping:
        async def record(self, line: Said, *, at: float | None = None) -> None:
            kept.append(line)

    provider = OrchestratedProvider(
        panel=DEFAULT_PANEL,
        transcriber=RecordingTranscriber(
            [Transcription(text="Margin is seventy percent.", final=True)]
        ),
        model=SilentModel(),
        transcript=Keeping(),
    )

    async with provider.open() as channel:
        [event async for event in channel.events()]

    assert Said(speaker=USER, text="Margin is seventy percent.") in kept
