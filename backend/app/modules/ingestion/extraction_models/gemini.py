"""Gemini, as an `ExtractionModel`.

Written for #61: extraction was built against Claude alone, on an account that
could not be funded, and `extraction_provider` was a single-valued `Literal` —
so switching was not configuration, it was a missing adapter. The failure mode
was the polite kind. `build_extraction_model` returns `None` without a key by
design, so the process boots, signs people in, accepts uploads, and grounds
nothing.

Everything vendor-shaped stops here: the parts layout, `inlineData`, the schema
dialect, the field names usage arrives under. Everything about *reading a deck*
lives in `reading.py` and is shared with the Claude adapter — including the rule
that matters most, that a model says where it found a figure and the text layer
is searched to find out whether that is true.

**The page still goes as image and text together, and that is not incidental.**
`docs/ingestion.md` chose a vision model because `Product.md` §3.2 wants chart
values per slide and a chart's numbers are in the pixels rather than the text
layer. An adapter that sent only text would authenticate, return claims, and
pass almost every test — while losing every figure a deck draws rather than
writes, permanently, because the source document is deleted once extraction
succeeds.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Sequence
from typing import Any

import httpx

from app.core.logging import get_logger
from app.modules.ingestion.extraction_model import ExtractionResult, ExtractionUsage
from app.modules.ingestion.extraction_models.reading import (
    DECK_FATAL_STATUSES,
    INSTRUCTION,
    Failed,
    charts_as_text,
    chunked,
    merged,
    to_claims,
)
from app.modules.ingestion.parsing import RenderedPage

log = get_logger(__name__, tag="ingestion")

PROVIDER = "gemini"

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

#: The header form rather than a `key=` query parameter, matching every other
#: Gemini adapter here: URLs reach access logs and error trackers, credentials
#: should not.
API_KEY_HEADER = "x-goog-api-key"

#: A vision model rather than a reasoning one, and cheap rather than strong.
#:
#: Extraction is not a judgement — the model's only job is pulling what a page
#: says into a typed claim, and every derived figure is arithmetic computed
#: elsewhere (`docs/auditor-grounding.md`). There is nothing here for thinking
#: to improve, and `docs/ingestion.md` names extraction as a per-user cost with
#: no revenue attached: the metering boundary is locked to live interrogation,
#: so a deck read by somebody who never starts a session is pure outflow.
DEFAULT_EXTRACTION_MODEL = "gemini-3.5-flash"

#: Generous, because the failure it prevents is a truncated claim list on a
#: dense deck — indistinguishable from a deck with fewer figures on it.
MAX_OUTPUT_TOKENS = 16384

#: How many pages go in one call.
#:
#: Inherited from the Claude adapter's arithmetic rather than re-derived, and
#: the binding constraint is the same: *output*, not context. At roughly six
#: claims a page and ~60 tokens a claim, forty pages already brushes
#: `MAX_OUTPUT_TOKENS`. Gemini's context is larger, which moves the slack in the
#: direction that does not bind.
#:
#: Estimated, not observed — `extraction_completed` logs claims per call, so
#: this becomes a measured figure once real decks have run.
PAGES_PER_CALL = 20

#: Calls in flight at once, per deck. The ceiling that matters is the
#: deployment's tokens-per-minute allowance, which is per organisation and
#: invisible from here.
DEFAULT_CONCURRENT_CALLS = 4

#: What a reply must look like.
#:
#: Two arrays rather than one with a `kind` field, for the reason the Claude
#: tool schema gives: a single array needs conditional schema to make `value`
#: required for a figure and `statement` for an assertion, and conditionals are
#: the part models honour least reliably. Two flat shapes, every field required
#: in each, is what comes back correct — and `to_claims` reads both.
_PAGE = {"type": "INTEGER", "description": "The page number this appears on."}
_QUOTE = {"type": "STRING", "description": "The text it was read from, quoted."}

_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "figures": {
            "type": "ARRAY",
            "description": "Every quantitative claim. One entry per figure.",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "page": _PAGE,
                    "metric": {
                        "type": "STRING",
                        "description": (
                            "What is measured, as written: 'gross margin', "
                            "'ARR', 'headcount'."
                        ),
                    },
                    "value": {
                        "type": "NUMBER",
                        "description": (
                            "The figure as a plain number. Write 1200000, "
                            "never '1.2M'."
                        ),
                    },
                    "unit": {
                        "type": "STRING",
                        "description": "As written: '%', '$', 'x', 'users'.",
                    },
                    "period": {
                        "type": "STRING",
                        # Nullable rather than omitted: a figure that states no
                        # period must be recordable as stating none, or the
                        # model invents one to satisfy the schema.
                        "nullable": True,
                        "description": (
                            "The period covered, as written: 'Q3 2026', "
                            "'FY2025'. Null if the figure states none."
                        ),
                    },
                    "quote": _QUOTE,
                },
                "required": ["page", "metric", "value", "unit", "quote"],
            },
        },
        "assertions": {
            "type": "ARRAY",
            "description": (
                "Every non-numeric claim: exclusivity, partnerships, patents "
                "and other IP, competitive absolutes ('nobody else offers X'), "
                "regulatory status, and commitments about the future. Skip "
                "description that asserts nothing."
            ),
            "items": {
                "type": "OBJECT",
                "properties": {
                    "page": _PAGE,
                    "subject": {
                        "type": "STRING",
                        "description": (
                            "The domain it belongs to: 'distribution', "
                            "'intellectual property', 'competition', "
                            "'regulatory', 'team'."
                        ),
                    },
                    "statement": {
                        "type": "STRING",
                        "description": (
                            "The claim in one sentence, as the deck makes it. "
                            "Do not soften or hedge it."
                        ),
                    },
                    "quote": _QUOTE,
                },
                "required": ["page", "subject", "statement", "quote"],
            },
        },
    },
    "required": ["figures", "assertions"],
}



#: How long one batch of pages may take to extract.
#:
#: The most generous here, and the least urgent: extraction is a background
#: sweep against material somebody uploaded, with its own stall detection above
#: it (`EXTRACTION_TIMEOUT`). A page batch is a vision call over real images.
#:
#: Explicit rather than inherited, because the shared client's five seconds
#: would fail this every single time.
MODEL_TIMEOUT_SECS = 180.0

class GeminiExtractionModel:
    """One client for the process, as the voice provider is."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_EXTRACTION_MODEL,
        concurrent_calls: int = DEFAULT_CONCURRENT_CALLS,
        http: httpx.AsyncClient,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._concurrent_calls = concurrent_calls
        self._http = http

    async def extract(self, pages: Sequence[RenderedPage]) -> ExtractionResult:
        """Read a whole deck, however many calls that takes.

        Chunking stops here. Nothing above — not the service, not the sweep —
        learns that a deck became more than one request, which is the property
        that lets a vendor with a different context window be a sibling module.
        """
        at_once = asyncio.Semaphore(self._concurrent_calls)
        readings = await asyncio.gather(
            *(
                self._read(chunk, at_once)
                for chunk in chunked(pages, PAGES_PER_CALL)
            )
        )
        return merged(
            readings, pages=pages, provider=PROVIDER, model=self._model
        )

    async def _read(
        self, pages: Sequence[RenderedPage], at_once: asyncio.Semaphore
    ) -> ExtractionResult | Failed:
        """One call, or why it did not happen.

        Failure is returned rather than raised so the other chunks still finish.
        They are in flight and already billable, and cancelling them would lose
        the usage for calls the invoice will still show — cost that cannot be
        reconciled is worse than cost that was wasted.
        """
        async with at_once:
            try:
                response = await self._http.post(
                    f"{BASE_URL}/{self._model}:generateContent",
                    headers={API_KEY_HEADER: self._api_key},
                    json={
                        "contents": [{"role": "user", "parts": _parts(pages)}],
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
                # The vendor is never named to the caller — CLAUDE.md. It is
                # named in the log, where it belongs.
                log.error(
                    "extraction_call_failed",
                    provider=PROVIDER,
                    status=exc.response.status_code,
                    pages=len(pages),
                    first_page=pages[0].number if pages else None,
                )
                return Failed(
                    retryable=exc.response.status_code not in DECK_FATAL_STATUSES
                )
            except httpx.HTTPError:
                # A timeout or a dropped connection: nothing about this deck, so
                # it waits and is tried again.
                log.error(
                    "extraction_call_unreachable",
                    provider=PROVIDER,
                    pages=len(pages),
                    first_page=pages[0].number if pages else None,
                )
                return Failed(retryable=True)

        payload = response.json()
        claims, dropped, corrected = to_claims(_reported(payload), pages=pages)

        if dropped:
            # A count, never the claims. These are figures read off a
            # confidential deck, and CLAUDE.md forbids ingested material in logs
            # — undetectable by key name, so never passed.
            log.warning(
                "extraction_claims_dropped", provider=PROVIDER, dropped=dropped
            )

        return ExtractionResult(
            claims=claims,
            dropped=dropped,
            corrected=corrected,
            usage=_usage_of(payload, model=self._model, pages=len(pages)),
        )


def _parts(pages: Sequence[RenderedPage]) -> list[dict[str, Any]]:
    """Every page as image and text, in that order.

    The image comes first within each page because the text is a caption for it:
    a model reading them the other way round anchors on the text layer, which is
    the half missing the chart values.
    """
    parts: list[dict[str, Any]] = []

    for page in pages:
        parts.append(
            {
                "inlineData": {
                    "mimeType": page.image_media_type,
                    "data": base64.b64encode(page.image).decode(),
                }
            }
        )
        parts.append(
            {"text": f"Page {page.number} text layer:\n{page.text}"}
        )
        if page.charts:
            parts.append(
                {
                    "text": (
                        f"Page {page.number} chart data, read from the file "
                        f"(exact):\n{charts_as_text(page.charts)}"
                    )
                }
            )

    return parts


def _reported(payload: dict[str, Any]) -> dict[str, Any]:
    """The object the model wrote, or nothing.

    Structured output is a request rather than a guarantee: a refusal, a stop on
    max tokens, or a plain prose reply are all shapes a provider can return. An
    exception here would surface inside the extraction sweep, where it marks
    nothing and leaves the material claimed until the requeue notices.
    """
    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        log.warning("extraction_returned_nothing", provider=PROVIDER)
        return {}

    try:
        reported = json.loads(text)
    except json.JSONDecodeError:
        # Never the text. It is a reading of a confidential deck either way.
        log.warning("extraction_reply_unparseable", provider=PROVIDER)
        return {}

    return reported if isinstance(reported, dict) else {}


def _usage_of(
    payload: dict[str, Any], *, model: str, pages: int
) -> ExtractionUsage:
    """What Google says the call cost.

    Read off their report rather than counted here: reimplementing a vendor's
    tokeniser to second-guess its own invoice can only ever agree or be wrong,
    and being wrong stays invisible until §4.3's reconciliation disagrees with
    the bill for a reason nobody can find.
    """
    usage = payload.get("usageMetadata") or {}
    return ExtractionUsage(
        provider=PROVIDER,
        model=model,
        input_tokens=int(usage.get("promptTokenCount") or 0),
        output_tokens=int(usage.get("candidatesTokenCount") or 0),
        pages=pages,
    )
