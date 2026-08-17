"""ElevenLabs Scribe, asked one question at a time.

Everything vendor-shaped in the one-shot hearing path stops here: the endpoint,
the multipart field names, `model_id`, `xi-api-key`.

**Why this is not `transcribers/elevenlabs.py`.** Same company, same job in the
abstract, and almost nothing in common concretely. That file speaks Scribe v2
*Realtime* over a WebSocket, with `input_audio_chunk`, base64 framing, commit
strategies and partial results — the entire shape exists to serve the room's
~1.5s budget. A coaching turn is a file upload against a REST endpoint, arriving
after the room has closed, with nothing to overlap. Folding them together would
mean one class holding two protocols so that a caller who never streams could
inherit a socket.

The cost of one vendor holding both is already recorded there: a single
incident takes the room's ears and its mouth at once, and now the debrief's ears
too. The seams are what keep that recoverable.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.errors import ProviderUnavailable
from app.core.logging import get_logger
from app.modules.voice.dictation import Heard

log = get_logger(__name__, tag="voice")

#: Named in logs so an operator can tell which vendor went quiet. Never in a
#: response — see `ProviderUnavailable`.
PROVIDER = "elevenlabs"

URL = "https://api.elevenlabs.io/v1/speech-to-text"

#: The batch model, not the realtime one the room uses.
#:
#: `scribe_v2_realtime` exists to emit partials inside a live budget and pays
#: accuracy for it. Nothing here is waiting: the user has finished speaking, the
#: coach has not started, and a second of extra care costs nothing anybody
#: notices. It is also the phase where a mis-heard word does the most damage —
#: sparring judges a re-answer against what it thinks was said, so a transcript
#: error becomes a coach telling somebody they got a number wrong that they got
#: right.
MODEL = "scribe_v1"

#: The field the vendor reads the audio from. Wrong and the call still returns
#: 200 with an empty transcript, which is why a test asserts it on the wire.
FILE_FIELD = "file"


class ElevenLabsDictation:
    """Hears one recorded turn."""

    def __init__(self, *, api_key: str, http: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._http = http

    async def hear(self, clip: bytes, *, media_type: str) -> Heard:
        """One clip, one answer."""
        try:
            response = await self._http.post(
                URL,
                headers={"xi-api-key": self._api_key},
                data={"model_id": MODEL},
                files={FILE_FIELD: ("turn", clip, media_type)},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # The vendor is named in the log and never to the client.
            log.warning(
                "dictation_refused",
                provider=PROVIDER,
                status=exc.response.status_code,
            )
            raise ProviderUnavailable(reason="dictation_error") from exc
        except httpx.HTTPError as exc:
            log.warning("dictation_unreachable", provider=PROVIDER)
            raise ProviderUnavailable(reason="dictation_unreachable") from exc

        return _heard(response.json())


def _heard(payload: Any) -> Heard:
    """What they said, and how long they took to say it.

    An empty transcript is an answer rather than a failure — somebody tapped
    record and said nothing, or the microphone was muted. Raising would tell the
    user the service is down when what happened is that it heard them perfectly.

    Whitespace-only is treated as empty for the same reason: a caller checking
    `if heard.text` should not have to know that a vendor returns a space for
    silence.

    Never logged, at any level. This is a spoken turn about somebody's own
    material — the same class as a transcript line, which CLAUDE.md forbids in
    logs and which no key-name redaction can catch.
    """
    if not isinstance(payload, dict):
        log.warning("dictation_reply_unreadable", provider=PROVIDER)
        return Heard(text="")

    text = payload.get("text")
    return Heard(
        text=text.strip() if isinstance(text, str) else "",
        seconds=float(payload.get("duration") or 0.0),
    )
