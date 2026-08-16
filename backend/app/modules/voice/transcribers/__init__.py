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
    trade `build_voice_provider` makes: the app boots without credentials — as
    every test and every local run needs it to — and the failure surfaces at the
    moment a room is dialled, typed and unnamed, where it can be settled and
    refunded. A half-built transcriber would instead fail in the middle of
    somebody's first metered interrogation.
    """
    if not settings.elevenlabs_api_key:
        return None

    return ElevenLabsTranscriber(api_key=settings.elevenlabs_api_key)
