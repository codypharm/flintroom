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
        model=settings.speech_model,
        default_voice_id=settings.elevenlabs_default_voice_id,
    )


def build_expressive_speaker(
    settings: Settings, http: httpx.AsyncClient
) -> Speaker | None:
    """The same vendor, the slower model, for lines nobody is waiting on.

    **A second instance rather than a wider seam.** `Speaker.speak` takes a
    voice and not a model, and it should stay that way: which model is a
    vendor's business, and a caller able to name one per call is a caller able
    to put the expressive model on the latency budget by accident. Choosing at
    construction is the same rule `CLAUDE.md` already applies to audit actors —
    context bound when the service is built, never passed per call.

    Shares the process-wide HTTP client with `build_speaker`, so the split
    costs an object rather than a connection pool.
    """
    if not settings.elevenlabs_api_key:
        return None

    return ElevenLabsSpeaker(
        api_key=settings.elevenlabs_api_key,
        http=http,
        model=settings.expressive_speech_model,
        default_voice_id=settings.elevenlabs_default_voice_id,
    )
