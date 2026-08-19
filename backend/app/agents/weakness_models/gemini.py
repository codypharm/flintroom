"""Gemini, as a `WeaknessReader`.

The second implementation of this seam, and the first time the seam has been
worth anything. `CLAUDE.md` puts the model layer behind an interface so a vendor
can be swapped on cost or availability; the Claude reader was written first
because the SDK and the tool-use pattern were already here for extraction, and
was replaced as the default the same day, when funding the Anthropic account
turned out not to be possible. Both remain. An interface with one implementation
has never been shown to be one.

**A reasoning model, and against the measured precedent for the panel.**
`panel_models/gemini.py` records `gemini-3.7-flash` at 2.11s with 383 thinking
tokens, losing to flash-lite at 0.82s — and losing on quality too, because a
panelist says one short hostile thing and a reasoning model writes a considered
paragraph. None of that transfers:

- **There is no clock.** One call, after the room has closed. Open Risk #3
  governs the session and nothing here.
- **The considered paragraph is the deliverable.** This exists to catch a
  fluent, specific, confidently *wrong* answer — the thing no rule in code can
  see. Reading fast is how it gets missed.
- **Once per session, not once per turn.** The panel sits inside the §4.4
  margins Open Risk #4 flags. This is a few thousand tokens against a room that
  cost roughly $0.48 to hold.

So the same model that lost the panel comparison is chosen here on purpose, for
the property that lost it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx

from app.agents.model import TurnUsage
from app.agents.weakness import (
    INSTRUCTION,
    Annotated,
    Weakness,
    WeaknessReading,
    render,
    to_judgements,
)
from app.core.errors import ProviderUnavailable
from app.core.logging import get_logger

log = get_logger(__name__, tag="debrief")

PROVIDER = "gemini"

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

#: The header form rather than a `key=` query parameter, matching
#: `panel_models/gemini.py`: URLs end up in access logs and error trackers, and
#: credentials should not.
API_KEY_HEADER = "x-goog-api-key"

#: The reasoning model, chosen for the reason it lost the panel comparison.
#:
#: Measured at 2.11s and 383 thinking tokens in `scripts/panel_spike.py`. On a
#: path with ~1.5s in total that was disqualifying; on a call that happens once,
#: offline, after the room, it is the whole point.
DEFAULT_DEBRIEF_MODEL = "gemini-3.7-flash"

#: Generous, and the generosity is the thinking rather than the answer.
#:
#: The reply is a handful of judgements of a sentence each — a few hundred tokens
#: at most. `panel_models/gemini.py` records the failure a tight ceiling causes
#: on a reasoning model: the budget is spent thinking, and the response comes
#: back empty with `finishReason: MAX_TOKENS`. Here that would be a debrief
#: silently reporting a flawless session.
MAX_OUTPUT_TOKENS = 8192

#: What the six categories mean, in the schema rather than the prompt.
#:
#: Generated from `Weakness` so a new member cannot be added without a meaning,
#: and so the two cannot drift apart silently.
WEAKNESS_MEANINGS = "Which kind of weakness this is. " + " ".join(
    f"'{value}': {meaning}"
    for value, meaning in (
        ("unanswered", "the presenter said nothing useful in reply, or moved on."),
        (
            "dismissed",
            "another panelist interrupted with a different priority before the "
            "presenter could answer. Use this whenever a note says so.",
        ),
        ("not_reached", "the session ended before they could answer."),
        (
            "contradicted",
            "a figure conflicts with another figure they gave, in the same "
            "answer or an earlier one — including arithmetic that does not work.",
        ),
        ("unsupported", "asserted with no figure, source or mechanism behind it."),
        ("evasive", "answered fluently, but not the question that was asked."),
    )
)

#: What a reply must look like. Gemini honours this as `responseSchema`, which is
#: how a category outside the vocabulary is refused at the vendor rather than
#: dropped by us — cheaper than parsing it and throwing it away, and it keeps the
#: enum in one place, since `Weakness` generates it.
_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "weak": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "ordinal": {"type": "INTEGER"},
                    "quote": {"type": "STRING"},
                    "weakness": {
                        "type": "STRING",
                        "enum": [weakness.value for weakness in Weakness],
                        # Measured 2026-08-17: without this, a question a
                        # colleague interrupted came back filed as `unanswered`
                        # — while its own `why` said "you were interrupted by
                        # another panelist before you had an opportunity to
                        # answer". The reading was right and the label was
                        # wrong, because six bare enum strings say nothing
                        # about what separates them.
                        #
                        # It matters more than a label usually would: the prep
                        # sheet groups on this, sparring branches on it, and
                        # #55 counts it. A dismissal filed as a dodge is the
                        # accusation #56 exists to prevent, arriving through
                        # the one field a reader skims.
                        "description": WEAKNESS_MEANINGS,
                    },
                    "why": {"type": "STRING"},
                },
                "required": ["ordinal", "quote", "weakness", "why"],
            },
        }
    },
    "required": ["weak"],
}



#: How long the debrief may take to read a room.
#:
#: **This is the bug that made the debrief a coin flip.** `main.py` builds one
#: `httpx.AsyncClient(timeout=5.0)` and shares it with everything — OAuth key
#: fetches, panel composition, synthesis, this. Five seconds is right for a
#: JWKS fetch and for `gemini-3.5-flash-lite` at 0.82s. It is not right for a
#: reasoning model reading a whole transcript: measured against a real
#: eighteen-line room, 4.97s and 5.35s on consecutive runs. The debrief loaded
#: or did not depending on the weather, and a longer room never loaded at all.
#:
#: Generous because there is nothing to be gained by being tight. This runs
#: once, offline, after the room has closed and settled — nobody is holding a
#: microphone waiting for it, and the alternative to waiting is a screen that
#: says the service is unavailable.
MODEL_TIMEOUT_SECS = 120.0

class GeminiWeaknessReader:
    """Reads a finished room and says what went badly in it."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_DEBRIEF_MODEL,
        http: httpx.AsyncClient,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._http = http

    async def rank(self, *, room: Sequence[Annotated]) -> WeaknessReading:
        """One call, offline, after everything."""
        payload = await self._generate(render(room))

        return WeaknessReading(
            judged=to_judgements(_reported(payload)), usage=_usage_of(payload)
        )

    async def _generate(self, room: str) -> dict[str, Any]:
        try:
            response = await self._http.post(
                f"{BASE_URL}/{self._model}:generateContent",
                headers={API_KEY_HEADER: self._api_key},
                json={
                    "contents": [{"role": "user", "parts": [{"text": room}]}],
                    "systemInstruction": {"parts": [{"text": INSTRUCTION}]},
                    "generationConfig": {
                        "maxOutputTokens": MAX_OUTPUT_TOKENS,
                        "candidateCount": 1,
                        "responseMimeType": "application/json",
                        "responseSchema": _SCHEMA,
                    },
                },
                timeout=MODEL_TIMEOUT_SECS,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # The vendor is named in the log and never to the client. A
            # `ProviderUnavailable` that said "gemini" would tell whoever is
            # probing what the architecture is, and would go stale the moment the
            # provider is swapped — which is the swap that produced this file.
            log.warning(
                "weakness_model_refused",
                provider=PROVIDER,
                model=self._model,
                status=exc.response.status_code,
            )
            raise ProviderUnavailable(reason="debrief_model_error") from exc
        except httpx.HTTPError as exc:
            log.warning(
                "weakness_model_unreachable", provider=PROVIDER, model=self._model
            )
            raise ProviderUnavailable(reason="debrief_model_unreachable") from exc

        return response.json()


def _reported(payload: dict[str, Any]) -> Any:
    """The object the model wrote, or nothing if it did not write one.

    Structured output is a request rather than a guarantee: a model refusing, or
    truncated mid-object, answers in prose that `json.loads` will not take. That
    has to cost the list and not the process — an unhandled raise here is a 500
    on the phase the user was told is free.
    """
    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        log.warning("weakness_reply_empty", provider=PROVIDER)
        return {}

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Never the text itself. It is a reading of a transcript either way, and
        # `CLAUDE.md` forbids transcript content in logs without exception.
        log.warning("weakness_reply_unparseable", provider=PROVIDER)
        return {}


def _usage_of(payload: dict[str, Any]) -> TurnUsage:
    """What Google says the call cost.

    Reported even when nothing could be parsed out of the reply. The provider
    charged for the call either way, and §4.3 reconciles against their invoice
    rather than against what we managed to read.
    """
    usage = payload.get("usageMetadata") or {}
    return TurnUsage(
        input_tokens=int(usage.get("promptTokenCount") or 0),
        output_tokens=int(usage.get("candidatesTokenCount") or 0),
    )
