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

import re
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

#: Models that act on audio tags — `[sighs]`, `[sceptical]` — rather than
#: reading them out.
#:
#: **Confirmed by ear against a live account, not from documentation**, and the
#: documentation was ambiguous enough to matter: the prompting guide calls tags
#: "an Eleven v3 feature" while the model page names v3 *Conversational* as the
#: only model supporting them. Neither says what Flash does when it receives one,
#: and the answer is the worst of the three possibilities — it speaks them. A
#: tagged take measured 5.7s against 3.6s for identical words, and the difference
#: is the model saying "sighs" and "sceptical" aloud.
#:
#: Anything not listed here has its tags stripped. Membership is opt-in for that
#: reason: a model added to this table by mistake makes panelists announce their
#: own stage directions, while one left out merely makes them flat.
TAG_PERFORMING_MODELS: frozenset[str] = frozenset({"eleven_v3", "eleven_v3_conversational"})

#: An audio tag, as the vendor writes it.
_TAG = re.compile(r"\[[^\]]*\]")

#: Runs of whitespace, including whatever a stripped tag left behind.
_GAP = re.compile(r"\s+")


def _spoken(text: str, *, model: str) -> str:
    """The line as this model should receive it.

    Stripped rather than refused. A line arriving with a tag is still a real
    challenge the user is owed, and losing four words of stage direction is a far
    smaller loss than losing the question — this is a live metered room.

    Whitespace is collapsed afterwards because a synthesiser reads it: a naive
    removal leaves a leading space and a doubled gap mid-sentence, which comes
    out as hesitation the panelist did not intend.
    """
    if model in TAG_PERFORMING_MODELS:
        return text
    return _GAP.sub(" ", _TAG.sub("", text)).strip()


#: Our casting vocabulary, resolved to this vendor's catalogue.
#:
#: **The only place in the codebase that knows an ElevenLabs voice id**, which is
#: the point: `agents/voices.py` names how somebody sounds, and swapping
#: synthesis vendors means writing a sibling of this table rather than touching a
#: single archetype — or, far more importantly, a single user's custom one.
#:
#: The names in comments are the vendor's own, kept because they are what an
#: operator sees in the dashboard when a voice needs replacing.
#:
#: **Two of these are library voices rather than premades, and that is a
#: durability difference worth knowing before adding a third.** The six premades
#: are shipped by the vendor and are as permanent as anything here gets. A
#: library voice belongs to whoever uploaded it and can be withdrawn by them
#: without warning — at which point `speak` falls back to the house voice and
#: logs `voice_uncast`, so the room survives but a panelist quietly loses the
#: identity `Product.md` §3.3 says the panel is made of. Nothing here can
#: prevent that; what it can do is make the trade explicit, since the vendor's
#: own premade catalogue carries only british, american and australian accents
#: and cannot cast this room at all.
ELEVENLABS_VOICES: dict[str, str] = {
    "measured": "onwK4e9ZLuTAKqWW03F9",  # Daniel  — British, formal, steady
    # Cast 2026-08-19 by the architect: the Technical Skeptic and the Growth
    # Maximalist are African American. Their portraits already were — the
    # reassignment in `portraits.ts` sat a Black woman and a Black man in these
    # two chairs — so this is the voice being brought into agreement with the
    # face rather than the other way round. That is the one direction that rule
    # normally forbids, and it is allowed here because a casting table is
    # configuration and a decision by the person who owns the product, not an
    # inference drawn from artwork.
    "precise": "NQMJRVvPew6HsaebYnZj",  # Cecily  — African American, middle-aged, confident (library)
    "assured": "EXAVITQu4vr4xnSDxMaL",  # Sarah   — American, mature, confident
    "eager": "f9aL8jTNAvSfAy338u1R",  # Derrick M — African American, young, confident (library)
    "brisk": "pNInz6obpgDQGcFmaJgB",  # Adam    — American, dominant, firm
    "smooth": "pFZP5JQG7iQjIQuC4Bku",  # Lily    — British, velvety
    "warm": "hpp4J3VqNfWAUOO0d1Us",  # Bella   — American, bright, open
    "dry": "pqHfZKP75CvOlQylNhV4",  # Bill    — American, older, crisp
}


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

    async def speak(self, *, text: str, voice: str | None) -> AsyncIterator[bytes]:
        """Stream one line as PCM, in the voice character it was given.

        `voice` is one of ours — `agents/voices.py` — and is resolved to a vendor
        id here and nowhere else.

        Anything this adapter does not recognise falls back to the house voice
        rather than refusing, and both routes to that are real: a character added
        to the vocabulary before this table learned it, or a custom archetype
        carrying a voice from a vendor we have since swapped away from. Neither
        should end a live metered interrogation. A casting mistake costs a
        panelist their timbre; refusing would cost the user their room.
        """
        vendor_voice = ELEVENLABS_VOICES.get(voice or "", self._default_voice_id)
        if vendor_voice is None or voice not in ELEVENLABS_VOICES:
            # Never the line itself — a panelist's words quote ingested material,
            # which CLAUDE.md forbids in logs. The character name is ours and
            # discloses nothing.
            log.warning("voice_uncast", provider=PROVIDER, voice=voice or "unset")

        url = f"{self._endpoint}/v1/text-to-speech/{vendor_voice}/stream"

        try:
            async with self._http.stream(
                "POST",
                url,
                params={"output_format": AUDIO_FORMAT},
                headers={"xi-api-key": self._api_key},
                json={
                    "text": _spoken(text, model=self._model),
                    "model_id": self._model,
                },
            ) as response:
                response.raise_for_status()
                # Chunk by chunk, never `aread()`. Streaming is what makes an
                # interrupted panelist stop: the room drops the iteration and the
                # sentence dies with it. Reading the whole body first would
                # synthesise every word before the first reached a phone, and
                # spend the entire budget on speech that may never be heard.
                #
                # Realigned to whole samples on the way past. PCM16 is two bytes
                # per sample and their HTTP chunks respect no such boundary —
                # measured live, 16 of 103 chunks came back odd-length, the
                # first among them. A consumer reading Int16s from a stream that
                # starts one byte late reads the low half of one sample against
                # the high half of the next for the rest of the utterance, which
                # is white noise rather than a glitch. It is what the first
                # audible room on a phone produced.
                #
                # The stray byte is carried, not dropped. Dropping would
                # re-align by discarding half a sample sixteen times a line,
                # trading a permanent fault for an intermittent one that is
                # harder to notice.
                carry = b""
                async for chunk in response.aiter_bytes():
                    whole = carry + chunk
                    carry = b""
                    if len(whole) % 2:
                        whole, carry = whole[:-1], whole[-1:]
                    if whole:
                        yield whole
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
