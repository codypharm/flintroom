"""ElevenLabs Scribe v2 Realtime.

Every vendor-shaped name in the transcription path stops here:
`input_audio_chunk`, `audio_base_64`, `partial_transcript`,
`committed_transcript`, `commit_strategy`. Nothing above this module learns
which company is listening, which is what keeps a swap a sibling file rather
than a rewrite — the same arrangement `providers/elevenlabs.py` and
`speakers/elevenlabs.py` already have.

Chosen on measurement, not on already holding the key: ~150ms partials at
$0.39/hr against Deepgram Nova-3's ~300ms at $0.46/hr, and `pcm_16000` spoken
natively, which is byte-for-byte what the relay carries in both directions.
AssemblyAI was ruled out on billing shape — it charges for how long the socket
stays open rather than for audio, and a hostile Q&A is mostly silence while
somebody works out an answer.

The cost of that choice, recorded so it is not discovered during an outage: the
room now rents its ears and its mouth from one company, so a single vendor
incident takes both at once. The seams are what make that recoverable rather
than fatal.

Translation is a pure function, separated from the socket that carries it. The
transport needs a network and a paid account; the interpretation is where the
bugs live and can be tested exhaustively without either.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode

import websockets
from websockets.exceptions import WebSocketException

from app.core.errors import ProviderUnavailable
from app.core.logging import get_logger
from app.modules.voice.transcription import Transcription

log = get_logger(__name__, tag="voice")

#: Named in logs so an operator can tell which vendor went quiet. Never in a
#: response — see `ProviderUnavailable`.
PROVIDER = "elevenlabs"

#: Signed 16-bit little-endian, 16 kHz, mono — the same constant the speaker and
#: the relay already carry. The phone records it, the transcriber hears it and
#: the synthesiser answers in it, so nothing on either leg transcodes.
AUDIO_FORMAT = "pcm_16000"

#: The rate implied by `AUDIO_FORMAT`, which their protocol wants repeated on
#: every chunk rather than read off the format it was handed at the handshake.
SAMPLE_RATE = 16_000

#: Their realtime endpoint. Regional variants exist (US, EU, India, Singapore)
#: and choosing one is a data-residency decision rather than a technical one, so
#: it stays configurable — the same way the Agents endpoint does.
DEFAULT_ENDPOINT = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"

#: Scribe v2 Realtime, at roughly 150ms.
#:
#: Pinned rather than left to their default, for the reason the speech model is
#: pinned: a silent change to it would surface as the room feeling slower, with
#: nothing in our own diff to explain it.
DEFAULT_TRANSCRIPTION_MODEL = "scribe_v2_realtime"

#: What language the room is held in, as the engine's own code.
#:
#: **Left unset, this engine auto-detects — and inventing a language is how it
#: fails.** `session_started` echoes `language_code: None` when no hint is
#: given, and on degraded audio the detector locks onto the wrong language and
#: then produces *fluent* text in it. That is far worse than returning nothing:
#: a confident wrong transcript is indistinguishable downstream from a real
#: one, so the panel answers it, the Auditor reads it, and the debrief is
#: grounded in it.
#:
#: Measured on a live room (92a8ef91, 2026-08-19). An English presenter over a
#: Bluetooth headset produced nine transcript lines of **Ukrainian**, opening
#: with "Алло!" — the same token a probe had got out of half a second of
#: digital silence earlier that day. The panel answered it faithfully and the
#: CFO said "Speak English." It was reported as the model hallucinating;
#: nothing in `app/agents/` was involved.
#:
#: **Only `language_code` is honoured.** `language` is accepted on the
#: handshake and silently ignored, which is the worst of both — it looks set
#: and is not.
#:
#: A setting rather than a constant because `Product.md` scopes v1 to English
#: and a deployment that outgrows that should not need a code change. Genuinely
#: multilingual rooms need this per session rather than per process, which is a
#: product decision and not this file's to make.
DEFAULT_LANGUAGE = "en"

#: How long the user must be quiet before the engine calls their turn over.
#:
#: **This sits directly inside the perceived latency budget and was not in the
#: 1.38s figure measured in `docs/panel-orchestration.md`.** That number starts
#: at the final transcript; a listener experiences the gap from the moment they
#: stop talking, which is this threshold plus that. Their SDK defaults to 1.5s,
#: which would put the room near 2.9s — roughly twice the ~1.5s threshold at
#: which `CLAUDE.md` says the illusion breaks.
#:
#: Measured at this value against live audio: the commit landed 0.77s after the
#: speech stopped, so the threshold is very nearly the whole term and tuning it
#: moves the budget. At 0.4s the commit came at 0.65s — engine overhead is real
#: but small.
#:
#: 0.7 is still chosen rather than derived, and it is a genuine trade rather than
#: a number to minimise: too low and the panel talks over somebody drawing breath
#: mid-answer, which is worse than a pause, because a room that interrupts you
#: cannot be argued with. Nothing measured so far bounds it from below —
#: synthetic speech has no mid-sentence pauses, so only a real person can say
#: where this becomes rude (Product.md §4.3).
SILENCE_THRESHOLD_SECS = 0.7

#: How close together two identical finals have to be to count as one utterance.
#:
#: The two message types this adapter accepts describe the *same* commit, so a
#: duplicate arrives immediately or not at all — well inside a second. Anything
#: further apart is a person saying the same short thing again, which in a
#: hostile Q&A is the common case rather than the exception.
#:
#: Deliberately short. The cost of being too generous is a silent room, which
#: the presenter cannot tell from a panel that is thinking; the cost of being
#: too tight is one duplicated turn, which is visible and cheap.
REPEAT_WINDOW_SECS = 2.0

#: Errors the room cannot continue through. The account is wrong, out of
#: credit, or the engine itself has failed — no amount of further audio
#: improves any of them, so the honest move is to end the session upstream,
#: where it gets settled and the minutes refunded.
FATAL_ERRORS: frozenset[str] = frozenset(
    {
        "auth_error",
        "quota_exceeded",
        "unaccepted_terms",
        "resource_exhausted",
        "session_time_limit_exceeded",
        "transcriber_error",
        "invalid_request",
    }
)


def to_transcription(message: dict[str, Any]) -> Transcription | None:
    """Translate one of their messages. `None` means nothing upstream acts on it."""
    match message.get("message_type"):
        case "partial_transcript":
            return Transcription(text=message["text"], final=False)

        case "committed_transcript" | "final_transcript":
            # Measured against live audio: under VAD only `committed_transcript`
            # arrives, and `final_transcript` never did. Both stay recognised
            # anyway. Their documentation lists both without saying which VAD
            # emits, so this costs nothing and covers a path we have not
            # exercised — reconnection, or a fall back to manual commit. The
            # failure it avoids is a room that hears every word and never
            # answers, which looks like a broken model rather than a missed
            # message type.
            #
            # If both ever did arrive for one utterance, the panel would
            # interrogate the same sentence twice: two model calls, two
            # syntheses, two metered turns. `ElevenLabsTranscriptionStream`
            # drops the repeat; see the note there.
            return Transcription(text=message["text"], final=True)

        case str(kind) if kind in FATAL_ERRORS:
            # Their message goes to the log and never to the client. It is
            # written for whoever holds the account, not for whoever is in the
            # room, and it names the vendor.
            log.error("transcription_failed", provider=PROVIDER, kind=kind)
            raise ProviderUnavailable(reason="transcription_failed")

    return None


class ElevenLabsTranscriptionStream:
    """One live transcription, over their WebSocket.

    Holds the socket and nothing else. Everything it decides — what goes on the
    wire, what a repeated final means, what a dropped connection turns into —
    is here; what the messages *say* is `to_transcription`.
    """

    def __init__(self, socket: Any, *, now: Any = None) -> None:
        self._socket = socket
        #: The last utterance declared final, and when — so one utterance
        #: committed twice is answered once, and a person repeating themselves
        #: a minute later is answered twice. See `results`.
        self._settled: str | None = None
        self._settled_at = 0.0
        #: Injected so the window can be tested without sleeping through it.
        #: Monotonic, because this measures an interval and a wall clock can
        #: step backwards mid-room.
        self._now = now or time.monotonic

    async def send_audio(self, pcm: bytes) -> None:
        """Forward the user's audio. Base64 is applied here and only here.

        `commit` is always false. Setting it would finalise the utterance at
        whatever byte happened to be in flight, handing the panel a fragment of
        a sentence to answer — the engine was asked to find those boundaries
        with VAD exactly so that this code never has to guess at them.
        """
        await self._socket.send(
            json.dumps(
                {
                    "message_type": "input_audio_chunk",
                    "audio_base_64": base64.b64encode(pcm).decode(),
                    "commit": False,
                    "sample_rate": SAMPLE_RATE,
                }
            )
        )

    async def results(self) -> AsyncIterator[Transcription]:
        """Their stream, translated, until the connection closes.

        Ends when the socket does, never when the user goes quiet. Silence is
        an ordinary part of a hostile Q&A, and deciding a room is abandoned
        belongs to the idle timeout, on a clock the session owns.

        A final repeating the one before it **within `REPEAT_WINDOW_SECS`** is
        dropped. Their protocol documents both `final_transcript` and
        `committed_transcript` without saying which VAD emits, so
        `to_transcription` accepts both; if both arrive for one utterance the
        panel would otherwise answer the same sentence twice — two model calls,
        two syntheses, two metered turns.

        **The window is the whole of it, and it was missing.** The first
        version compared against the last final and kept it forever, which
        silently swallowed a presenter answering two different questions the
        same way — and a hostile Q&A is full of "Yes.", "No.", "Twenty.". Its
        own docstring claimed such a user was "heard both times" while using
        the failing case as the example. Reported from a device as the room
        going quiet: no turn, no reply, and nothing to distinguish it from a
        panel that is thinking.
        """
        try:
            async for frame in self._socket:
                if (result := to_transcription(json.loads(frame))) is None:
                    continue
                if not result.final:
                    yield result
                    continue
                at = self._now()
                if (
                    result.text == self._settled
                    and at - self._settled_at < REPEAT_WINDOW_SECS
                ):
                    log.debug("transcription_repeat_dropped", provider=PROVIDER)
                    continue
                self._settled = result.text
                self._settled_at = at
                yield result
        except WebSocketException as exc:
            # The vendor's exception stops here. CLAUDE.md: provider failures
            # surface unnamed, because naming one exposes internal architecture
            # and goes stale the moment the provider is swapped.
            log.warning("transcription_dropped", provider=PROVIDER, error=type(exc).__name__)
            raise ProviderUnavailable(reason="transcription_dropped") from exc


class ElevenLabsTranscriber:
    """Dials Scribe. One instance per process.

    Built once in the application lifespan, like the voice provider and the auth
    verifiers: an instance per room would rebuild connection state on every
    session, and this is the object that will hold pooling.

    `connect` is injected so the dialling path is substitutable. Nothing in the
    test suite reaches the real endpoint — doing so needs a paid account, and
    what it proves is what the §4.3 spike exists to measure.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_TRANSCRIPTION_MODEL,
        language: str = DEFAULT_LANGUAGE,
        silence_threshold_secs: float = SILENCE_THRESHOLD_SECS,
        endpoint: str = DEFAULT_ENDPOINT,
        connect: Any = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._language = language
        self._silence_threshold_secs = silence_threshold_secs
        self._endpoint = endpoint
        self._connect = connect or websockets.connect

        # Stated once per process, from the object that resolved it rather than
        # from whoever passed it, so the line says what will actually be dialled.
        #
        # The threshold decides whether the panel talks over somebody mid-answer
        # and costs 0.30s of latency between its plausible values, and it was
        # invisible: a real session was judged comfortable in the belief it ran
        # at 0.4 when `.env` said 0.7, and nothing anywhere could settle which
        # had been heard. Never the key — a startup line is exactly where a
        # credential gets attached as "useful context".
        log.info(
            "transcriber_ready",
            provider=PROVIDER,
            model=self._model,
            language=self._language,
            silence_threshold_secs=self._silence_threshold_secs,
        )

    @asynccontextmanager
    async def open(self) -> AsyncIterator[ElevenLabsTranscriptionStream]:
        """Open a transcription, and make sure it is closed again.

        A context manager for the reason the voice provider's `open` is one: a
        stream left open is a room still running on their invoice, and that must
        not depend on the caller tidying up on every path out — including the
        failing ones.
        """
        query = urlencode(
            {
                "model_id": self._model,
                "audio_format": AUDIO_FORMAT,
                # Never omitted. See `DEFAULT_LANGUAGE` — an unhinted engine
                # detects, and a wrong detection is answered rather than
                # noticed.
                "language_code": self._language,
                "commit_strategy": "vad",
                "vad_silence_threshold_secs": self._silence_threshold_secs,
            }
        )
        try:
            async with self._connect(
                f"{self._endpoint}?{query}",
                additional_headers={"xi-api-key": self._api_key},
            ) as socket:
                yield ElevenLabsTranscriptionStream(socket)
        except (WebSocketException, OSError) as exc:
            # Includes DNS failures, refused connections and TLS errors, all of
            # which the session treats identically: the room never opened.
            log.warning("transcription_dial_failed", provider=PROVIDER, error=type(exc).__name__)
            raise ProviderUnavailable(reason="transcription_dial_failed") from exc
