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
from app.modules.ingestion.schemas import ClaimKind

log = get_logger(__name__, tag="ingestion")

PROVIDER = "claude"

#: Generous, because the failure it prevents is a truncated claim list on a
#: dense deck — which looks exactly like a deck with fewer figures on it, and
#: nothing downstream can tell the difference. Raised when assertions were added
#: alongside figures: they are the more numerous kind on most slides, so the
#: output roughly trebled while the input did not move.
MAX_OUTPUT_TOKENS = 16384

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

INSTRUCTION = (
    "Each page is given as an image and its text layer. Read both: chart values "
    "are usually in the image only. Record what the pages claim with the "
    "record_claims tool — figures in `figures`, non-numeric claims in "
    "`assertions`. Record exactly what is stated; never derive, convert, total, "
    "or infer a figure, and never soften an assertion."
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

        claims, dropped, corrected = to_claims(_tool_input(message), pages=pages)

        if dropped:
            # A count, never the claims themselves. These are figures read off a
            # confidential deck, and CLAUDE.md forbids ingested material
            # contents in logs — undetectable by key name, so never passed.
            log.warning("extraction_claims_dropped", provider=PROVIDER, dropped=dropped)

        # Counts only, never the claims. These are figures and statements read
        # off a confidential deck; CLAUDE.md forbids ingested material contents
        # in logs, and unlike a secret they are not detectable by key name.
        #
        # Neither number is an error. `corrected` is the attribution check
        # working, and it is the only measure of how far the model's own page
        # numbers can be trusted — the number that should decide whether a page
        # stays the locator at all. `unverified` is how much of a deck is
        # grounded in text nothing could confirm, which is Open Risk #2 made
        # countable rather than argued about.
        log.info(
            "extraction_completed",
            provider=PROVIDER,
            pages=len(pages),
            claims=len(claims),
            corrected=corrected,
            unverified=sum(not claim.quote_verified for claim in claims),
        )

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


def _normalized(text: str) -> str:
    """Collapse everything a layout engine did to the whitespace.

    Extracted text breaks lines wherever the column did, and a model tidies a
    quote into one line before writing it down. Without this the search below
    matches nothing on a real deck while passing every test written with clean
    strings — the worst kind of silent no-op.
    """
    return " ".join(text.split()).casefold()


def _located(
    claim: ExtractedClaim, pages: Sequence[RenderedPage]
) -> ExtractedClaim:
    """Answer two questions with one search: are these the deck's words, and where.

    They are different questions and the answers can differ. A running header
    appears on every slide — that the deck says it is not in doubt, while *which*
    page it came from genuinely is. Marking that unverified would throw away a
    fact we have over one we do not.

    Move a claim to the page its quote is actually on, if that is knowable.

    Which page a piece of text is on is a fact about the deck, not an opinion of
    the model's — so where the text layer settles it, it is looked up rather
    than believed. The same *"model extracts, code computes"* split
    `docs/auditor-grounding.md` applies to arithmetic, applied to the locator.

    Two cases deliberately leave the model's answer alone:

    - **The quote is on no page.** A figure read off a chart lives in the pixels
      and appears in no text layer, which is the entire reason a vision model is
      here. Those stay best-effort.
    - **The quote is on several pages.** A running header or a repeated summary
      line is on every slide. Ambiguous evidence must not override the model,
      which at least looked at the images; picking the first match would be
      inventing a citation with the confidence of a lookup.
    """
    quote = _normalized(claim.claim.quote)
    if not quote:
        return claim

    found = [page.number for page in pages if quote in _normalized(page.text)]
    if not found:
        return claim

    located = {"quote_verified": True}
    if len(found) == 1:
        located["page"] = found[0]
    return claim.model_copy(update=located)


def to_claims(
    payload: dict[str, Any], *, pages: Sequence[RenderedPage]
) -> tuple[tuple[ExtractedClaim, ...], int, int]:
    """The model's answer, as typed claims plus a count of what would not type.

    Pure, and separated from the transport for the reason the ElevenLabs adapter
    separates its own translation: the socket cannot be tested without an
    account, and the interpretation is where the bugs that matter live.

    One malformed entry drops rather than raising. Raising would discard an
    entire extraction that has already been paid for, and the material would
    fail for a reason no re-upload fixes. The count is returned because a silent
    drop is how a deck quietly grounds nothing.

    `page_numbers` is which pages were actually sent. The page on a claim is *reported
    by the model* — it reads "Page 2 text layer:" and writes back where it found
    a figure — so nothing else would stop a four-page deck yielding a claim on
    page 99. That number is not bookkeeping: it is what a panelist says out
    loud, and "defend what you claimed on page 99" against a four-page deck
    costs the room its credibility in one line. Out of range is dropped rather
    than clamped, because a guessed citation is worse than a missing claim —
    CLAUDE.md: do not ship interrogation logic that cannot cite its source.

    The pages themselves rather than a count, so this survives being handed a
    slice of a deck. Once pages are chunked across calls (task #31), a chunk
    holding pages 51-100 has a length of fifty and page numbers starting at
    fifty-one — and a length check would drop every claim in it.
    """
    claims: list[ExtractedClaim] = []
    dropped = 0
    corrected = 0
    page_numbers = {page.number for page in pages}

    for field, kind in (("figures", ClaimKind.QUANTITATIVE), ("assertions", ClaimKind.ASSERTION)):
        entries = payload.get(field)
        if not isinstance(entries, list):
            # A missing array is not a malformed claim — a deck of photographs
            # legitimately has no figures on it. Only entries are counted.
            continue

        for entry in entries:
            try:
                # Copied rather than popped. `entry` belongs to the caller's
                # payload, and mutating it would leave the provider's reply
                # subtly different from what arrived — which matters most when
                # something goes wrong and that payload is what gets inspected.
                fields = {k: v for k, v in entry.items() if k != "page"}
                found = ExtractedClaim(
                    page=entry["page"], claim={**fields, "kind": kind}
                )
                # Located first, then the range check — a claim the quote
                # places on a real page is a good claim, however it was
                # originally labelled, and checking first would throw it away.
                placed = _located(found, pages)
                corrected += placed.page != found.page

                if placed.page not in page_numbers:
                    raise ValueError("claim cites a page the deck does not have")
                claims.append(placed)
            except Exception:  # noqa: BLE001 - see below
                # Deliberately broad, and deliberately not re-raised. Everything
                # here is somebody else's output: a bad field raises
                # `ValidationError`, a non-mapping entry raises `AttributeError`,
                # a missing page raises `KeyError`, and an impossible page
                # raises the `ValueError` above. The correct response to all
                # four is the same. Nothing is swallowed — the count is
                # returned, and logged by the caller.
                dropped += 1

    return tuple(claims), dropped, corrected
