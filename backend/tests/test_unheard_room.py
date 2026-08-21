"""The room saying it has heard nothing at all, inside a live room. #77.

`test_room_hearing.py` proves the latch and records why the task's original
premise was wrong. This proves the room reports it, and — the part actually
worth guarding — that it stops reporting it the instant somebody speaks.

The failure to avoid is not subtle and this codebase has already committed it
once: `app/src/lib/audio/hearing.ts` shipped a warning that fired at the room's
own noise floor, so the room told the architect it could barely hear them,
continuously, while they were saying nothing. A warning that fires at the wrong
time teaches people to ignore the one that matters.
"""

from __future__ import annotations

import pytest

from app.agents.archetypes import DEFAULT_PANEL
from app.agents.context import Grounding
from app.modules.voice.events import Attention
from app.modules.voice.hearing import UNHEARD_AFTER_SECONDS
from app.modules.voice.orchestrated import (
    BYTES_PER_SAMPLE,
    SAMPLE_RATE,
    OrchestratedChannel,
)
from app.modules.voice.transcription import Transcription

from tests.test_orchestrated_channel import (
    FakeTranscription,
    ScriptedPanelModel,
    events_of,
)
from tests.test_opening_in_the_room import held, opening

pytestmark = pytest.mark.asyncio

SILENT_SECOND = bytes(SAMPLE_RATE * BYTES_PER_SAMPLE)


def a_room(results=()) -> OrchestratedChannel:
    return OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(list(results)),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        floor=held(),
    )


async def silence_for(channel: OrchestratedChannel, seconds: int) -> None:
    for _ in range(seconds):
        await channel.send_audio(SILENT_SECOND)


async def test_a_room_that_has_only_just_opened_is_only_listening():
    """Every room starts here, and a room that announced a dead microphone on
    its first buffer would announce it on every session ever run."""
    channel = a_room()
    await silence_for(channel, 1)

    assert channel._attention() is Attention.LISTENING  # noqa: SLF001


async def test_a_room_that_has_never_heard_anything_says_so():
    channel = a_room()
    await silence_for(channel, UNHEARD_AFTER_SECONDS)

    assert channel._attention() is Attention.UNHEARD  # noqa: SLF001


async def test_one_word_ends_it_for_the_rest_of_the_room():
    """The whole safety argument in one test.

    On the configuration this product ships, an ordinary pause is byte-for-byte
    identical to a dead microphone — `docs/echo-cancellation.md` measured a
    quiet S24+ at exact digital zero. So the only thing that makes this warning
    safe to show is that a proven microphone can never un-prove itself, however
    long the presenter then thinks.
    """
    channel = a_room()
    await channel.send_audio(b"\x11\x22" * SAMPLE_RATE)
    await silence_for(channel, UNHEARD_AFTER_SECONDS * 3)

    assert channel._attention() is Attention.LISTENING  # noqa: SLF001


async def test_a_panelist_speaking_outranks_it():
    """A room mid-turn is working, and saying two things about one moment is
    the bug that took a speaking panelist off the screen."""
    channel = a_room([Transcription(text=opening(12), final=True)])
    await silence_for(channel, UNHEARD_AFTER_SECONDS)

    events = await events_of(channel)

    # The presenter was heard, so the warning is off regardless — and this is
    # the room that proves the two orderings never had to be reconciled.
    assert channel._attention() is not Attention.UNHEARD  # noqa: SLF001
    assert events


async def test_the_room_reaches_the_presenter_before_the_transcriber_invents_one():
    """#77 measured 36-37 seconds of silence before the transcriber committed an
    empty final. `_listen` drops that final, so without this the presenter's
    only signal is a room that never speaks."""
    channel = a_room()
    await silence_for(channel, 36)

    assert channel._attention() is Attention.UNHEARD  # noqa: SLF001
