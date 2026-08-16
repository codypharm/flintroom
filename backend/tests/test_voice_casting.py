"""Voices named in our vocabulary, resolved to a vendor's inside its adapter.

The decision, taken when custom archetypes were designed: a saved voice choice is
**our** name, never a vendor identifier. Shipped archetypes are configuration in
one file, so a vendor swap there is a find-and-replace — but a Pro user's custom
archetype is a row they own, and a vendor id stored in one turns a swap into a
migration over customer content.

That is the lock-in this codebase refuses everywhere else: `user_id` is never a
foreign key to `auth.users`, storage is behind a presigned URL, the conversation
is behind `VoiceChannel`. A vendor id in a user row would be the one place it
came back.
"""

from __future__ import annotations

import httpx
import pytest

from app.agents.archetypes import LIBRARY
from app.agents.voices import CASTABLE, Voice
from app.modules.voice.speakers.elevenlabs import ELEVENLABS_VOICES, ElevenLabsSpeaker




def speaker_over(**kwargs):
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"\x01")

    http = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return ElevenLabsSpeaker(api_key="secret", http=http, **kwargs), seen


def test_no_archetype_names_a_vendor():
    """The property this whole file exists for.

    Asserted against the vocabulary rather than by pattern-matching what an
    ElevenLabs id looks like, because the next vendor's ids will look different
    and the rule is the same for all of them.
    """
    for archetype in LIBRARY:
        assert archetype.voice in CASTABLE, (
            f"{archetype.name} is cast as {archetype.voice!r}, "
            "which is not a voice character we publish"
        )


def test_every_castable_voice_can_actually_be_spoken():
    """A name with no vendor behind it is a panelist who silently sounds generic.

    The two halves are edited in different files for different reasons — one is a
    casting vocabulary, the other is a vendor's catalogue — so nothing but this
    stops them drifting apart.
    """
    unmapped = [voice for voice in CASTABLE if voice not in ELEVENLABS_VOICES]

    assert unmapped == [], f"voice characters with no vendor voice behind them: {unmapped}"


@pytest.mark.asyncio
async def test_the_adapter_resolves_our_name_to_the_vendors_id():
    """The seam doing its job: our vocabulary in, their identifier on the wire."""
    speaker, seen = speaker_over()

    async for _ in speaker.speak(text="Against what basis?", voice=Voice.MEASURED):
        pass

    assert ELEVENLABS_VOICES[Voice.MEASURED] in str(seen[0].url)


@pytest.mark.asyncio
async def test_a_voice_the_vendor_does_not_know_falls_back_rather_than_failing():
    """A casting mistake costs a panelist their timbre, never the room.

    Reachable two ways, and neither should end a live metered interrogation: a
    name added to the vocabulary before this adapter learned it, or a custom
    archetype carrying a voice from a vendor we have since swapped away from.
    """
    speaker, seen = speaker_over(default_voice_id="house_voice")

    async for _ in speaker.speak(text="And the margin?", voice="not_a_voice"):
        pass

    assert "house_voice" in str(seen[0].url)
