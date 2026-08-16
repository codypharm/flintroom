"""ElevenLabs streaming text-to-speech.

The half of this vendor we still want. Owning the conversation loop replaced
their *Agents* product, not the company: distinct per-archetype voices are the
reason `CLAUDE.md` locked the voice provider in, and they are not decoration. The
interrogation surface is hands-free by design — the phone is face-down on a desk
— so voice is the only channel carrying *who* is challenging you.

Plain `httpx` rather than their SDK, matching `panel_models/gemini.py`. One POST
that streams bytes back needs no client library, and an SDK here would be a
dependency, a release cadence and an exception hierarchy adopted to save a
handful of lines.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from app.core.errors import ProviderUnavailable
from app.core.logging import get_logger

log = get_logger(__name__, tag="voice")

#: Named in logs so an operator can tell which vendor refused. Never in a
#: response — see `ProviderUnavailable`.
PROVIDER = "elevenlabs"

DEFAULT_ENDPOINT = "https://api.elevenlabs.io"

#: Signed 16-bit little-endian, 16 kHz, mono — byte-for-byte what the relay
#: carries and what the phone plays. The PCM-throughout transport decision means
#: nothing between here and the speaker transcodes, and putting a decode in the
#: middle of a budget that is already over 1.5s would be the wrong place to save
#: uplink bandwidth.
AUDIO_FORMAT = "pcm_16000"

#: Flash v2.5, at roughly 75ms against ~280ms for the conversational model.
#:
#: Pinned rather than left to the vendor's default, which is neither the fastest
#: nor stable across releases — a silent change to it would surface as the room
#: feeling slower with nothing in our own diff to explain it. Verified current
#: rather than remembered: `eleven_turbo_v2_5`, the obvious guess, is deprecated.
DEFAULT_SPEECH_MODEL = "eleven_flash_v2_5"


class ElevenLabsSpeaker:
    """Speaks one line at a time. One instance per process.

    The `http` client is injected rather than built here, so connections are
    pooled across every room in the process. A client per utterance would pay a
    TLS handshake inside each turn's latency budget, which is the one place this
    adapter could quietly cost more than the model it is speaking for.
    """

    def __init__(
        self,
        *,
        api_key: str,
        http: httpx.AsyncClient,
        model: str = DEFAULT_SPEECH_MODEL,
        default_voice_id: str | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
    ) -> None:
        self._api_key = api_key
        self._http = http
        self._model = model
        self._default_voice_id = default_voice_id
        self._endpoint = endpoint

    async def speak(
        self, *, text: str, voice_id: str | None
    ) -> AsyncIterator[bytes]:
        """Stream one line as PCM, in the voice it was given.

        `voice_id` is nullable because the archetype library ships without voices
        assigned. Falling back is deliberate: refusing would mean no archetype
        could be heard until every one of them had a voice, and a panel that all
        sounds alike is worse than a real room but far better than a silent one.
        """
        voice = voice_id or self._default_voice_id
        url = f"{self._endpoint}/v1/text-to-speech/{voice}/stream"

        try:
            async with self._http.stream(
                "POST",
                url,
                params={"output_format": AUDIO_FORMAT},
                headers={"xi-api-key": self._api_key},
                json={"text": text, "model_id": self._model},
            ) as response:
                response.raise_for_status()
                # Chunk by chunk, never `aread()`. Streaming is what makes an
                # interrupted panelist stop: the room drops the iteration and the
                # sentence dies with it. Reading the whole body first would
                # synthesise every word before the first reached a phone, and
                # spend the entire budget on speech that may never be heard.
                async for chunk in response.aiter_bytes():
                    yield chunk
        except httpx.HTTPStatusError as exc:
            # The vendor goes to the log and never to the client. Naming it in a
            # response tells whoever is probing what our architecture is, and it
            # goes stale the moment synthesis is swapped — which is the swap the
            # `Speaker` seam exists to permit.
            #
            # Never the line itself: a panelist's words quote ingested material
            # directly, and CLAUDE.md forbids that in logs.
            log.warning(
                "speech_refused",
                provider=PROVIDER,
                model=self._model,
                status=exc.response.status_code,
            )
            raise ProviderUnavailable(reason="speech_error") from exc
        except httpx.HTTPError as exc:
            # A timeout or a dropped connection — nothing to read off it, so it
            # is caught separately. Left broad within httpx's own hierarchy
            # rather than enumerated: a transport error class we have not met yet
            # should surface as a 502 the finalizer can refund against, never as
            # a 500.
            log.warning("speech_unreachable", provider=PROVIDER, model=self._model)
            raise ProviderUnavailable(reason="speech_unreachable") from exc
