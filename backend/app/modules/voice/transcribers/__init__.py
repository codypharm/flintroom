"""Concrete transcribers.

One module per vendor, mirroring `voice/providers/` and `voice/speakers/`.
Everything vendor-shaped — wire formats, message names, authentication, base64 —
lives inside its own file here, so that replacing Scribe with Deepgram Nova-3 is
a sibling module and a branch below rather than an edit to anything that runs a
room.
"""

from app.core.config import Settings
from app.modules.voice.transcribers.elevenlabs import ElevenLabsTranscriber
from app.modules.voice.transcription import Transcriber


def build_transcriber(settings: Settings) -> Transcriber | None:
    """The configured transcriber, or nothing if this deployment has no key.

    `None` rather than a transcriber holding an empty key, which is the same
    trade `build_speaker` makes: the app boots without credentials — as
    every test and every local run needs it to — and the failure surfaces at the
    moment a room is dialled, typed and unnamed, where it can be settled and
    refunded. A half-built transcriber would instead fail in the middle of
    somebody's first metered interrogation.
    """
    if not settings.elevenlabs_api_key:
        return None

    # Only when configured, so an unset deployment gets the adapter's own
    # measured default rather than a copy of it kept in `Settings` — one float
    # in one place, and the reasoning next to the vendor it was measured
    # against.
    threshold = (
        {"silence_threshold_secs": settings.vad_silence_threshold_secs}
        if settings.vad_silence_threshold_secs is not None
        else {}
    )
    return ElevenLabsTranscriber(api_key=settings.elevenlabs_api_key, **threshold)
