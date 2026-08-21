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

import asyncio

import pytest

from app.agents.archetypes import DEFAULT_PANEL, LIBRARY
from app.agents.context import Grounding
from app.modules.voice.events import AgentTranscript, Attention
from app.modules.voice.hearing import UNHEARD_AFTER_SECONDS
from app.modules.voice.orchestrated import (
    BYTES_PER_SAMPLE,
    SAMPLE_RATE,
    OrchestratedChannel,
)
from app.modules.voice.transcription import Transcription

from tests.test_orchestrated_channel import (
    FakeSpeaker,
    FakeTranscription,
    ScriptedPanelModel,
    events_of,
)
from tests.test_opening_in_the_room import held, held_open, opening

pytestmark = pytest.mark.asyncio

SILENT_SECOND = bytes(SAMPLE_RATE * BYTES_PER_SAMPLE)


def a_room(results=(), **kwargs) -> OrchestratedChannel:
    return OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=FakeTranscription(list(results)),
        model=ScriptedPanelModel(),
        grounding=Grounding(),
        floor=held(),
        **kwargs,
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


# --- what the room says out loud, once the quiet has run long enough ---------


def a_quiet_room() -> tuple[OrchestratedChannel, FakeSpeaker]:
    """A room that will nudge on its next beat, with a voice to do it in."""
    speaker = FakeSpeaker()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=held_open([]),
        model=ScriptedPanelModel(),
        speaker=speaker,
        opener_speaker=speaker,
        grounding=Grounding(),
        floor=held(),
        heartbeat_seconds=0.02,
    )
    # Sixty seconds is the shipped threshold; this room treats any quiet as long
    # enough, so the test is about which question it asks and not about a clock.
    channel._heard_at = -1e9  # noqa: SLF001
    return channel, speaker


async def spoken_in(channel: OrchestratedChannel) -> list[str]:
    collecting = asyncio.create_task(events_of(channel))
    await asyncio.sleep(0.1)
    channel._transcription.release.set()  # noqa: SLF001
    events = await collecting
    return [e.text for e in events if isinstance(e, AgentTranscript)]


async def test_a_room_that_has_heard_nothing_does_not_ask_them_to_say_more():
    """THE BUG. Every nudge line asks the presenter to speak — "take your time,
    but say something", "come on, talk to me" — and nothing consulted whether
    the room had ever heard anything before picking one.

    So somebody whose microphone was dead, who had been talking for a full
    minute, was told at sixty seconds to do the thing that had already failed.
    """
    channel, _ = a_quiet_room()
    await silence_for(channel, UNHEARD_AFTER_SECONDS)

    said = await spoken_in(channel)

    asked = [line for line in said if any(line in one.nudges for one in DEFAULT_PANEL)]
    assert not asked, f"told a silent presenter to speak: {asked}"


async def test_it_tells_them_the_room_is_getting_nothing_instead():
    channel, _ = a_quiet_room()
    await silence_for(channel, UNHEARD_AFTER_SECONDS)

    said = await spoken_in(channel)

    told = [line for line in said if any(line in one.unheard for one in DEFAULT_PANEL)]
    assert len(told) == 1, f"expected exactly one, got {told}"


async def test_it_is_still_the_ordinary_question_for_a_room_that_has_heard_them():
    """The default, and the one that must not regress. Somebody thinking hard
    about a hostile question has a working microphone; sending them to check it
    is the same failure inverted, and it would fire on every long pause."""
    channel, _ = a_quiet_room()
    await channel.send_audio(b"\x11\x22" * SAMPLE_RATE)
    await silence_for(channel, UNHEARD_AFTER_SECONDS * 2)

    said = await spoken_in(channel)

    asked = [line for line in said if any(line in one.nudges for one in DEFAULT_PANEL)]
    assert len(asked) == 1, f"expected exactly one, got {asked}"


async def test_it_is_said_by_somebody_at_the_table():
    """A voice belonging to nobody seated would be a narrator, which
    `nudge_from` and `opener_from` both refuse for the same reason.

    Checked against the **seated** panel rather than the whole library, which is
    the only version of this that can fail: every line in `LIBRARY` would pass a
    laxer check while still being spoken by somebody who is not in the room.
    """
    channel, speaker = a_quiet_room()
    await silence_for(channel, UNHEARD_AFTER_SECONDS)

    said = await spoken_in(channel)

    told = [line for line in said if any(line in one.unheard for one in LIBRARY)]
    assert told, "the room said nothing about hearing nothing"
    for line in told:
        assert any(line in one.unheard for one in DEFAULT_PANEL), line
    # Out loud, not merely captioned — that is the whole reason this is spoken.
    assert speaker.spoke
