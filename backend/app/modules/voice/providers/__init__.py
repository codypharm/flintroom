"""Concrete voice providers.

One module per vendor. Everything vendor-shaped — wire formats, event names,
authentication, base64 — lives inside its own file here, so that swapping to
Gemini Live is a sibling module rather than an edit to the relay (CLAUDE.md →
Architecture Decisions).
"""

from app.core.config import Settings
from app.modules.voice.provider import VoiceProvider
from app.modules.voice.providers.elevenlabs import ElevenLabsProvider


def build_voice_provider(settings: Settings) -> VoiceProvider | None:
    """The configured provider, or nothing if this deployment has no credentials.

    The one place that decides which vendor is in use. Adding Gemini Live as
    the documented fallback is a branch here plus a sibling module — no caller
    of `VoiceProvider` changes, which is the property the whole interface
    exists to preserve.
    """
    if not (settings.elevenlabs_api_key and settings.elevenlabs_agent_id):
        return None

    return ElevenLabsProvider(
        api_key=settings.elevenlabs_api_key,
        agent_id=settings.elevenlabs_agent_id,
    )
