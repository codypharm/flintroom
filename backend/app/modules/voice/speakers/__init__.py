"""Concrete speech synthesisers.

One module per vendor, mirroring `voice/providers/`. Everything vendor-shaped —
endpoints, wire formats, model names, authentication — lives inside its own file
here, so that swapping synthesis is a sibling module rather than an edit to the
room.
"""

import httpx

from app.core.config import Settings
from app.modules.voice.speakers.elevenlabs import ElevenLabsSpeaker
from app.modules.voice.speech import Speaker


def build_speaker(settings: Settings, http: httpx.AsyncClient) -> Speaker | None:
    """The configured synthesiser, or nothing if this deployment has no key.

    `None` rather than a refusal, and the room treats it as a first-class
    configuration: an `OrchestratedChannel` without a speaker still transcribes,
    still routes, still composes, and still sends captions. Every part of the
    panel can be developed and read in a transcript before a synthesis key
    exists, which is the difference between one missing credential costing the
    voice and costing the product.
    """
    if not settings.elevenlabs_api_key:
        return None

    return ElevenLabsSpeaker(
        api_key=settings.elevenlabs_api_key,
        http=http,
        default_voice_id=settings.elevenlabs_default_voice_id,
    )
