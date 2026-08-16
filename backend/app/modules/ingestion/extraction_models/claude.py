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

import base64
from collections.abc import Sequence
from typing import Any

import httpx
from anthropic import AsyncAnthropic, AnthropicError

from app.core.errors import ProviderUnavailable
from app.core.logging import get_logger
from app.modules.ingestion.extraction_model import (
    ExtractedClaim,
    ExtractionResult,
    ExtractionUsage,
)
from app.modules.ingestion.parsing import RenderedPage

log = get_logger(__name__, tag="ingestion")

PROVIDER = "claude"

#: Generous, because the failure it prevents is a truncated claim list on a
#: dense deck — which looks exactly like a deck with fewer figures on it.
MAX_OUTPUT_TOKENS = 8192

TOOL_NAME = "record_claims"

#: The tool is the output format. A schema the provider enforces beats asking
#: for JSON in prose and parsing whatever comes back, and it is why `to_claims`
#: below is short enough to be obviously correct.
CLAIM_TOOL: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": (
        "Record every quantitative claim stated on these pages. One entry per "
        "figure. Do not compute, infer, or combine figures — record only what "
        "is written."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "integer",
                            "description": "The page number the figure appears on.",
                        },
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
                        "quote": {
                            "type": "string",
                            "description": "The text the figure was read from.",
                        },
                    },
                    "required": ["page", "metric", "value", "unit", "quote"],
                },
            }
        },
        "required": ["claims"],
    },
}

INSTRUCTION = (
    "Each page is given as an image and its text layer. Read both: chart values "
    "are usually in the image only. Record every quantitative claim with the "
    "record_claims tool. Record figures exactly as stated — never derive, "
    "convert, or total them."
)


class ClaudeExtractionModel:
    """One client for the process, as the voice provider is."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = model
        # `http_client` exists so the tests drive a real SDK client over a
        # transport that never leaves the process. Translation is where the bugs
        # live, and it should not need an account to exercise.
        self._client = AsyncAnthropic(api_key=api_key, http_client=http_client)

    async def extract(self, pages: Sequence[RenderedPage]) -> ExtractionResult:
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=MAX_OUTPUT_TOKENS,
                tools=[CLAIM_TOOL],
                tool_choice={"type": "tool", "name": TOOL_NAME},
                messages=[{"role": "user", "content": _content(pages)}],
            )
        except AnthropicError as exc:
            # Never named to the caller. CLAUDE.md: a vendor in an error message
            # exposes internal architecture and goes stale the moment the
            # provider is swapped, which this interface exists to allow.
            log.error("extraction_provider_failed", provider=PROVIDER)
            raise ProviderUnavailable(reason="extraction_unavailable") from exc

        claims, dropped = to_claims(_tool_input(message))

        if dropped:
            # A count, never the claims themselves. These are figures read off a
            # confidential deck, and CLAUDE.md forbids ingested material
            # contents in logs — undetectable by key name, so never passed.
            log.warning("extraction_claims_dropped", provider=PROVIDER, dropped=dropped)

        return ExtractionResult(
            claims=claims,
            dropped=dropped,
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


def to_claims(payload: dict[str, Any]) -> tuple[tuple[ExtractedClaim, ...], int]:
    """The model's answer, as typed claims plus a count of what would not type.

    Pure, and separated from the transport for the reason the ElevenLabs adapter
    separates its own translation: the socket cannot be tested without an
    account, and the interpretation is where the bugs that matter live.

    One malformed entry drops rather than raising. Raising would discard an
    entire extraction that has already been paid for, and the material would
    fail for a reason no re-upload fixes. The count is returned because a silent
    drop is how a deck quietly grounds nothing.
    """
    entries = payload.get("claims")
    if not isinstance(entries, list):
        return (), 0

    claims: list[ExtractedClaim] = []
    dropped = 0
    for entry in entries:
        try:
            claims.append(ExtractedClaim.model_validate(entry))
        except Exception:  # noqa: BLE001 - see below
            # Deliberately broad, and deliberately not re-raised. Everything
            # here is somebody else's output: `model_validate` raises
            # `ValidationError` for a bad field and `AttributeError` for a
            # non-mapping entry, and the correct response to both is the same.
            # Nothing is swallowed — the count is returned and logged upstream.
            dropped += 1

    return tuple(claims), dropped
