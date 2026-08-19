"""Gemini as a `ClaimReader`.

Everything vendor-shaped stops here: the URL, the header, the response schema,
where the JSON hides in the reply.

**Plain `httpx`, for the reason `panel_models/gemini.py` gives.** This runs
inside a live metered room on every utterance, so exponential backoff is the
wrong behaviour rather than a missing one — a retry landing two seconds later
has already missed the turn it was for. What is left is one POST with a JSON
body, and a transport a test can substitute.

**Structured output is requested and never trusted.** `responseSchema` makes the
shape overwhelmingly likely, not certain, and the failure it would otherwise
cause is the specific one `docs/auditor-grounding.md` says the grounding story
cannot survive: a malformed figure reaching the comparison logic and a panelist
asserting, live and confidently, that a number moved when it did not. So every
claim is validated by Pydantic on the way in and a bad one is dropped rather
than repaired — a repaired figure is a guess wearing a type.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.agents.auditor import ClaimReading
from app.agents.model import TurnUsage
from app.core.errors import ProviderUnavailable
from app.core.logging import get_logger
from app.modules.ingestion.schemas import QuantitativeClaim

log = get_logger(__name__, tag="auditor")

PROVIDER = "gemini"

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

#: The header rather than `Authorization: Bearer` or a `key=` query parameter,
#: which keeps the credential out of URLs — the part of a request that reaches
#: access logs and error trackers. Same choice, same reason, as the panel model.
API_KEY_HEADER = "x-goog-api-key"

#: The cheapest, fastest model in the family, and the choice is not a compromise.
#:
#: This job is transcription-shaped rather than reasoning-shaped: the figures are
#: already in the sentence, and the task is to write them down with their unit
#: and period attached. `panel_models/gemini.py` measured a reasoning model as
#: both slower and *worse* at a task with one right answer, and this task has
#: less judgement in it than that one did.
#:
#: It also runs on every utterance inside a live room, where the panel model
#: runs once per turn — so it is the most latency- and cost-sensitive model call
#: in the product.
DEFAULT_READER_MODEL = "gemini-3.5-flash-lite"

#: Enough for the figures in one spoken sentence. A person does not state twelve
#: numbers in a breath, and a ceiling stops a runaway reply from becoming a
#: latency spike inside a metered room.
MAX_READING_TOKENS = 512

#: What the model is allowed to return, declared to the vendor rather than
#: merely asked for in prose.
#:
#: `period` is nullable rather than omitted: headcount today has no period, and
#: a schema demanding one would push the model into inventing "2026" — which is
#: worse than absent, because `comparable_to` would then compare two figures on
#: the strength of a fabricated match.
_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "metric": {"type": "string"},
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                    "period": {"type": "string", "nullable": True},
                },
                "required": ["quote", "metric", "value", "unit"],
            },
        }
    },
    "required": ["claims"],
}

_INSTRUCTION = (
    "You are transcribing figures out of one sentence of speech, not "
    "interpreting them. For each number the speaker states as a fact about "
    "their business, record what it measures, its value, its unit, the period "
    "it covers if they said one, and the words they used.\n\n"
    "Record only what was said. Never convert, never compute a figure from "
    "other figures, never infer a period that was not spoken, and never repair "
    "a number that sounds wrong. If the sentence contains no figure, return an "
    "empty list — that is the ordinary case and not a failure.\n\n"
    "`metric` is what is being measured, in the speaker's own terms: "
    "\"gross margin\", \"ARR\", \"headcount\". `value` is a bare number: 1.2 "
    "million is 1200000. `unit` is one of: percent, usd, eur, gbp, multiple, "
    "count. `quote` is the speaker's own words for that figure."
)



#: How long the Auditor may take to read one utterance.
#:
#: This runs *during* a room, beside the turn rather than in front of it, so a
#: slow call costs a catch rather than a question. Twenty seconds matches the
#: composer's for the same reason: past it something is wrong, and the room
#: carries on without the finding.
#:
#: Explicit rather than inherited. `auditor_invocations` has been zero in every
#: session recorded so far, and a silently-timing-out reader is one of the
#: things that would look exactly like that.
MODEL_TIMEOUT_SECS = 20.0

class GeminiClaimReader:
    """Reads figures out of speech, and does nothing else with them."""

    def __init__(
        self,
        *,
        api_key: str,
        http: httpx.AsyncClient,
        model: str = DEFAULT_READER_MODEL,
    ) -> None:
        self._api_key = api_key
        self._http = http
        self._model = model

    async def read(
        self, *, said: str, known_metrics: tuple[str, ...] = ()
    ) -> ClaimReading:
        payload = await self._ask(said, known_metrics)
        return ClaimReading(
            claims=_claims_of(payload),
            usage=_usage_of(payload),
        )

    async def _ask(self, said: str, known_metrics: tuple[str, ...]) -> dict[str, Any]:
        try:
            response = await self._http.post(
                f"{BASE_URL}/{self._model}:generateContent",
                headers={API_KEY_HEADER: self._api_key},
                json={
                    "contents": [
                        {"role": "user", "parts": [{"text": _prompt(said, known_metrics)}]}
                    ],
                    "systemInstruction": {"parts": [{"text": _INSTRUCTION}]},
                    "generationConfig": {
                        "maxOutputTokens": MAX_READING_TOKENS,
                        "candidateCount": 1,
                        "responseMimeType": "application/json",
                        "responseSchema": _RESPONSE_SCHEMA,
                    },
                },
                timeout=MODEL_TIMEOUT_SECS,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Never the utterance, and never the vendor to the client.
            # `CLAUDE.md`: a provider failure must not name the provider, and a
            # transcript must not reach a log at all.
            log.warning(
                "claim_reader_refused",
                provider=PROVIDER,
                model=self._model,
                status=exc.response.status_code,
            )
            raise ProviderUnavailable(reason="claim_reader_error") from exc
        except httpx.HTTPError as exc:
            log.warning("claim_reader_unreachable", provider=PROVIDER, model=self._model)
            raise ProviderUnavailable(reason="claim_reader_unreachable") from exc

        return response.json()


def _prompt(said: str, known_metrics: tuple[str, ...]) -> str:
    """The utterance, and the names the speaker has already used.

    Measured live, this is the difference between catching the canonical
    contradiction and missing it: *"our gross margin held at sixty-one
    percent"* followed by *"the margin is closer to seventy percent"* produced
    `gross margin` and `margin`, two metrics that are never compared, and the
    room said nothing.

    Names only, never the figures. What the model is being asked is *which
    metric is this*, and showing it the previous values would invite it to
    reconcile them — arithmetic, on the wrong side of the line, and precisely
    what the extract/compute split exists to prevent.

    Omitted entirely when there is nothing to list, rather than sent as an empty
    section. Every session's first utterance takes that path, so it is the
    commonest case and not an edge, and a prompt saying "already mentioned:
    none" invites a model to treat the absence as meaningful.
    """
    if not known_metrics:
        return said

    named = "\n".join(f"- {metric}" for metric in known_metrics)
    return (
        f"Metrics this speaker has already named in this conversation:\n{named}\n\n"
        "If a figure below refers to one of those, use that exact name for it. "
        "Only when it is plainly a different measurement should you name a new "
        "one — gross margin and net margin are not the same thing.\n\n"
        f"What they just said:\n{said}"
    )


def _claims_of(payload: dict[str, Any]) -> tuple[QuantitativeClaim, ...]:
    """Whatever survives validation, and nothing else.

    Three ways this returns nothing, and all three are ordinary: the sentence
    held no figure, the model answered with prose instead of JSON, or every
    entry was malformed. None of them is worth ending a metered interrogation
    over, and the Auditor's caller already treats an empty reading as the
    common case.
    """
    body = _text_of(payload)
    if not body:
        return ()

    try:
        entries = json.loads(body).get("claims") or []
    except (json.JSONDecodeError, AttributeError):
        # Asked for JSON, answered with an apology or a code fence. Counted
        # rather than raised: a steady stream of these is a prompt that has
        # stopped working, and it would otherwise be invisible.
        log.warning("claim_reading_unparseable", provider=PROVIDER)
        return ()

    claims = []
    for entry in entries:
        try:
            claims.append(QuantitativeClaim.model_validate(entry))
        except ValidationError:
            # One bad entry must not cost the good ones in the same sentence.
            # Never the entry itself — it is the user's own words.
            log.warning("claim_dropped_malformed", provider=PROVIDER)
    return tuple(claims)


def _text_of(payload: dict[str, Any]) -> str:
    """The body, out of the shape Google returns it in."""
    candidates = payload.get("candidates") or []
    parts = (candidates[0].get("content", {}) if candidates else {}).get("parts") or []
    return "".join(part.get("text", "") for part in parts).strip()


def _usage_of(payload: dict[str, Any]) -> TurnUsage:
    """What Google says the call cost, read off their report rather than counted.

    Absent fields fall back to zero rather than raising: a missing count is one
    reading recorded cheap, and a raise is a live room ended over bookkeeping.
    """
    usage = payload.get("usageMetadata") or {}
    return TurnUsage(
        input_tokens=int(usage.get("promptTokenCount") or 0),
        output_tokens=int(usage.get("candidatesTokenCount") or 0),
    )
