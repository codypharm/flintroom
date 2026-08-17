"""Claude, as an `ExtractionModel`.

Everything vendor-shaped stops here: the tool schema, the content-block layout,
`tool_use`, base64. A second vendor is a sibling of this file, not an edit to
anything that calls it.

Chosen first because it takes each page as **text and image together**
(`docs/ingestion.md`), and that pairing is the whole reason this module renders
anything: `Product.md` §3.2 asks for chart data per slide, and a chart's values
are not in a PDF's text layer. An integration sending only text works, passes,
and silently loses every figure the deck draws rather than writes.

**The model extracts; code computes.** Its only job is pulling figures into a
typed claim. Every derived figure — a multiple, a runway, an implied valuation —
is ordinary arithmetic elsewhere, which is what makes arithmetic hallucination
impossible rather than discouraged (`docs/auditor-grounding.md`).
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from anthropic import AsyncAnthropic, AnthropicError

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

PROVIDER = "claude"

#: Generous, because the failure it prevents is a truncated claim list on a
#: dense deck — which looks exactly like a deck with fewer figures on it, and
#: nothing downstream can tell the difference. Raised when assertions were added
#: alongside figures: they are the more numerous kind on most slides, so the
#: output roughly trebled while the input did not move.
MAX_OUTPUT_TOKENS = 16384

#: How many pages go in one call.
#:
#: Set by the *output* limit, not the context window, which is the part that
#: surprises. A rendered page costs roughly `width × height / 750` input tokens
#: — measured at 2,534 for a letter page through this pipeline, around 1,850 for
#: a 16:9 slide — so twenty pages is ~55k input against a 200k context, with
#: room to spare. Output is what binds: at ~6 claims a page and ~60 tokens a
#: claim, forty pages already brushes `MAX_OUTPUT_TOKENS` and fifty exceeds it.
#:
#: Twenty leaves roughly twice the headroom on the binding constraint, so a
#: genuinely dense deck can produce double the estimate and still not truncate.
#: That matters more than it sounds: a truncated claim list looks exactly like a
#: deck with fewer figures on it, and the source is deleted afterwards.
#:
#: Estimated, not observed. `extraction_completed` logs claims per call, so
#: after real decks have run this becomes a measured claims-per-page figure and
#: the number can be set from data rather than arithmetic — the §4.3 argument,
#: applied to context instead of cost.
PAGES_PER_CALL = 20

#: Calls in flight at once, **per deck**, when nothing configures it. A 300-page
#: deck is fifteen calls; run one after another that is minutes of wall clock
#: for somebody who uploaded a deck in order to rehearse against it now.
#:
#: This is not the fleet's ceiling and must not be mistaken for one. The
#: semaphore is created per `extract` call, and the API key is one credential
#: for the whole deployment — so the rate-limit allowance is spent by every user
#: at once, not by each user separately. A user works one deck at a time; fifty
#: users on a busy evening do not. Whatever decides how many materials the
#: extraction sweep claims per pass is choosing the real number.
#:
#: **Unvalidated against token throughput.** One call held continuously costs
#: `55,000 × 60 / call_seconds` tokens a minute, so at a low allowance and a
#: fast call four is already over the line with a single deck and no other
#: users. It is `extraction_concurrent_calls` in `Settings` for exactly that
#: reason — see the reasoning there, and lower it the evening it starts
#: rate-limiting.
DEFAULT_CONCURRENT_CALLS = 4

#: Retries per call, set here rather than inherited.
#:
#: The SDK already retries twice by default with exponential backoff, on the
#: usual set — 408, 429, 5xx, connection failures. Raised rather than
#: hand-rolled: a second retry layer on top would multiply into nine attempts
#: for one page range, and none of them would know about the others.
#:
#: Four because of what a failure now costs. One chunk that gives up discards
#: every other chunk's claims, so a transient overload on call eight of fifteen
#: throws away fourteen calls that were already paid for. Backoff caps at eight
#: seconds, so four attempts is a few seconds of insurance against that.
MAX_RETRIES = 4

TOOL_NAME = "record_claims"

#: The tool is the output format. A schema the provider enforces beats asking
#: for JSON in prose and parsing whatever comes back, and it is why `to_claims`
#: below is short enough to be obviously correct.
_PAGE = {
    "type": "integer",
    "description": "The page number this appears on.",
}
_QUOTE = {
    "type": "string",
    "description": "The text it was read from, quoted.",
}

#: Two arrays rather than one array with a `kind` field.
#:
#: A single array needs `oneOf` to make `value` required for a figure and
#: `statement` required for an assertion, and conditional JSON Schema is the
#: part models honour least reliably. Two flat schemas, every field required in
#: each, is the shape that comes back correct — and `to_claims` reads both.
CLAIM_TOOL: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": (
        "Record what these pages claim. Figures go in `figures`; statements "
        "that are not numbers go in `assertions`. Record only what is written — "
        "never derive, convert, total, or infer."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "figures": {
                "type": "array",
                "description": "Every quantitative claim. One entry per figure.",
                "items": {
                    "type": "object",
                    "properties": {
                        "page": _PAGE,
                        "metric": {
                            "type": "string",
                            "description": (
                                "What is measured, as written: 'gross margin', "
                                "'ARR', 'headcount'."
                            ),
                        },
                        "value": {
                            "type": "number",
                            "description": (
                                "The figure as a plain number. Write 1200000, "
                                "never '1.2M'."
                            ),
                        },
                        "unit": {
                            "type": "string",
                            "description": "As written: '%', '$', 'x', 'users'.",
                        },
                        "period": {
                            "type": ["string", "null"],
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
                "type": "array",
                "description": (
                    "Every non-numeric claim: exclusivity, partnerships, "
                    "patents and other IP, competitive absolutes ('nobody "
                    "else offers X'), regulatory status, and commitments about "
                    "the future. Skip description that asserts nothing."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "page": _PAGE,
                        "subject": {
                            "type": "string",
                            "description": (
                                "The domain it belongs to: 'distribution', "
                                "'intellectual property', 'competition', "
                                "'regulatory', 'team'."
                            ),
                        },
                        "statement": {
                            "type": "string",
                            "description": (
                                "The claim in one sentence, as the deck makes "
                                "it. Do not soften or hedge it."
                            ),
                        },
                        "quote": _QUOTE,
                    },
                    "required": ["page", "subject", "statement", "quote"],
                },
            },
        },
        "required": ["figures", "assertions"],
    },
}

class ClaudeExtractionModel:
    """One client for the process, as the voice provider is."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        concurrent_calls: int = DEFAULT_CONCURRENT_CALLS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = model
        self._concurrent_calls = concurrent_calls
        # `http_client` exists so the tests drive a real SDK client over a
        # transport that never leaves the process. Translation is where the bugs
        # live, and it should not need an account to exercise.
        self._client = AsyncAnthropic(
            api_key=api_key, http_client=http_client, max_retries=MAX_RETRIES
        )

    async def extract(self, pages: Sequence[RenderedPage]) -> ExtractionResult:
        """Read a whole deck, however many calls that takes.

        Chunking stops here. Nothing above this — not the service, not the
        sweep — learns that a deck became more than one request, which is the
        property that lets a vendor with a larger context be a sibling module
        rather than a change to the pipeline.
        """
        chunks = chunked(pages, PAGES_PER_CALL)
        at_once = asyncio.Semaphore(self._concurrent_calls)
        readings = await asyncio.gather(
            *(self._read(chunk, at_once) for chunk in chunks)
        )
        return merged(readings, pages=pages, provider=PROVIDER, model=self._model)

    async def _read(
        self, pages: Sequence[RenderedPage], at_once: asyncio.Semaphore
    ) -> ExtractionResult | Failed:
        """One call, or why it did not happen.

        Failure is returned rather than raised so the other chunks still finish.
        They are in flight and already billable, and cancelling them would lose
        the usage numbers for calls the invoice will still show — cost that
        cannot be reconciled is worse than cost that was wasted.
        """
        async with at_once:
            try:
                message = await self._client.messages.create(
                    model=self._model,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    tools=[CLAIM_TOOL],
                    tool_choice={"type": "tool", "name": TOOL_NAME},
                    messages=[{"role": "user", "content": _content(pages)}],
                )
            except AnthropicError as exc:
                # The vendor is never named to the caller. CLAUDE.md: a vendor
                # in an error message exposes internal architecture and goes
                # stale the moment the provider is swapped, which this interface
                # exists to allow. It is named in the log, where it belongs.
                status = getattr(exc, "status_code", None)
                log.error(
                    "extraction_call_failed",
                    provider=PROVIDER,
                    status=status,
                    pages=len(pages),
                    first_page=pages[0].number if pages else None,
                )
                return Failed(retryable=status not in DECK_FATAL_STATUSES)

        claims, dropped, corrected = to_claims(_tool_input(message), pages=pages)

        if dropped:
            # A count, never the claims themselves. These are figures read off a
            # confidential deck, and CLAUDE.md forbids ingested material
            # contents in logs — undetectable by key name, so never passed.
            log.warning("extraction_claims_dropped", provider=PROVIDER, dropped=dropped)

        return ExtractionResult(
            claims=claims,
            dropped=dropped,
            corrected=corrected,
            usage=ExtractionUsage(
                provider=PROVIDER,
                model=self._model,
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
                pages=len(pages),
            ),
        )

def _content(pages: Sequence[RenderedPage]) -> list[dict[str, Any]]:
    """One instruction, then every page as image and text.

    The image comes first within each page because the text is a caption for it:
    a model reading them the other way round anchors on the text layer, which is
    the half that is missing the chart values.
    """
    blocks: list[dict[str, Any]] = [{"type": "text", "text": INSTRUCTION}]

    for page in pages:
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": page.image_media_type,
                    "data": base64.b64encode(page.image).decode(),
                },
            }
        )
        blocks.append(
            {"type": "text", "text": f"Page {page.number} text layer:\n{page.text}"}
        )
        if page.charts:
            blocks.append(
                {
                    "type": "text",
                    "text": (
                        f"Page {page.number} chart data, read from the file "
                        f"(exact):\n{charts_as_text(page.charts)}"
                    ),
                }
            )

    return blocks


def _tool_input(message: Any) -> dict[str, Any]:
    """The tool call's arguments, or nothing.

    `tool_choice` asks for exactly one, and this still does not assume it
    arrived. A refusal, a stop on max tokens, or a plain text reply are all
    shapes a provider can return, and an `IndexError` here would surface inside
    the extraction sweep — where it marks nothing and leaves the material
    claimed until the requeue notices.
    """
    for block in message.content:
        if getattr(block, "type", None) == "tool_use":
            return block.input
    log.warning("extraction_returned_no_tool_call", provider=PROVIDER)
    return {}
