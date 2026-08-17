"""Concrete dictation adapters.

One module per vendor, mirroring `transcribers/` and `speakers/`. The room
already rents its ears from ElevenLabs; this is the same company answering a
different shape of question, and it is a separate file because the endpoint,
the body and the failure modes have nothing in common with the socket.
"""

import httpx

from app.core.config import Settings
from app.modules.voice.dictation import Dictation
from app.modules.voice.dictations.elevenlabs import ElevenLabsDictation


def build_dictation(
    settings: Settings, *, http: httpx.AsyncClient | None = None
) -> Dictation | None:
    """The configured adapter, or nothing if this deployment has no key.

    Absent rather than fatal, matching every other optional edge: auth,
    balances, the room and the ranked list all work without it. What a
    deployment without one loses is the *spoken* half of the debrief — the
    ranked list still reads — which is worth logging once at boot rather than
    discovering when somebody holds down a button and nothing happens.
    """
    if not settings.elevenlabs_api_key or http is None:
        return None
    return ElevenLabsDictation(api_key=settings.elevenlabs_api_key, http=http)
