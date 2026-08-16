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

#: Statuses that mean *this request*, not *right now*. Retrying produces the
#: same refusal, so a deck that hits one is not worth requeueing — provided
#: something else in the same deck succeeded, which is the evidence that the
#: request shape itself is fine.
#:
#: Everything else — 429, 529, 5xx, timeouts, connection failures, and a
#: credential we got wrong — is a "come back later", because none of them are
#: anything the user's file did.
DECK_FATAL_STATUSES = frozenset({400, 413, 422})

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


@dataclass(frozen=True)
class _Failed:
    """A call that gave up, and whether later could go differently.

    A record rather than `None`, because "it did not work" and "it will never
    work" are different answers and collapsing them is what turns a busy
    minute into somebody re-uploading a deck that was fine.
    """

    retryable: bool


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
        chunks = _chunked(pages, PAGES_PER_CALL)
        at_once = asyncio.Semaphore(self._concurrent_calls)
        readings = await asyncio.gather(
            *(self._read(chunk, at_once) for chunk in chunks)
        )
        return self._merged(readings, pages=pages)

    async def _read(
        self, pages: Sequence[RenderedPage], at_once: asyncio.Semaphore
    ) -> ExtractionResult | _Failed:
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
                return _Failed(retryable=status not in DECK_FATAL_STATUSES)

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

    def _merged(
        self,
        readings: Sequence[ExtractionResult | _Failed],
        *,
        pages: Sequence[RenderedPage],
    ) -> ExtractionResult:
        """Every call's answer, as one deck's worth.

        An incomplete deck always drops its claims: a partially-read deck
        grounds less than the user believes, nothing downstream can tell, and
        the source is deleted on success — the gap would be permanent and
        invisible.

        What varies is whether it is worth trying again, and that is decided by
        *why* calls failed rather than by how many:

        - **A call the API refused outright** — 400, 413, 422. About this
          content, and retrying produces the same refusal forever. Not
          retryable, but only when some sibling chunk succeeded: that success is
          the evidence the request shape works. A malformed tool schema fails
          every call identically, and reading that as "this deck is unreadable"
          would permanently fail every deck uploaded while the bug was live.
        - **Anything else** — rate limits, timeouts, an overloaded provider, a
          credential we got wrong. Not the deck's fault, so the material waits
          and is tried again.

        It never raises. A caller that has to handle both a return value and an
        exception for the same question is one that will handle one of them
        wrong, and this is the seam a second vendor implements.
        """
        answered = [r for r in readings if isinstance(r, ExtractionResult)]
        failures = [r for r in readings if isinstance(r, _Failed)]

        complete = not failures
        # Deny by default, applied to destroying somebody's deck: unretryable
        # requires both a permanent refusal *and* a sibling that worked.
        # `all`, not `any`: one permanent refusal outranks any number of
        # transient ones, because retrying cannot fix it and the deck would
        # spin through the sweep failing identically.
        retryable = bool(failures) and (
            not answered or all(failure.retryable for failure in failures)
        )
        claims = (
            tuple(claim for reading in answered for claim in reading.claims)
            if complete
            else ()
        )
        dropped = sum(reading.dropped for reading in answered)
        corrected = sum(reading.corrected for reading in answered)

        # Counts only, never the claims. These are figures and statements read
        # off a confidential deck; CLAUDE.md forbids ingested material contents
        # in logs, and unlike a secret they are not detectable by key name.
        #
        # None of these is an error on its own. `corrected` is the attribution
        # check working, and it is the only measure of how far the model's own
        # page numbers can be trusted — the number that should decide whether a
        # page stays the locator at all. `unverified` is how much of a deck is
        # grounded in text nothing could confirm, which is Open Risk #2 made
        # countable rather than argued about. `calls` is what task #31 added,
        # and the number that says whether the chunk size is set anywhere near
        # right once real decks have run through it.
        log.info(
            "extraction_completed",
            provider=PROVIDER,
            pages=len(pages),
            calls=len(readings),
            answered=len(answered),
            complete=complete,
            claims=len(claims),
            corrected=corrected,
            unverified=sum(not claim.quote_verified for claim in claims),
        )

        return ExtractionResult(
            claims=claims,
            dropped=dropped,
            corrected=corrected,
            complete=complete,
            retryable=retryable,
            usage=ExtractionUsage(
                provider=PROVIDER,
                model=self._model,
                input_tokens=sum(r.usage.input_tokens for r in answered),
                output_tokens=sum(r.usage.output_tokens for r in answered),
                pages=len(pages),
                calls=len(readings),
            ),
        )


def _chunked(
    pages: Sequence[RenderedPage], size: int
) -> list[Sequence[RenderedPage]]:
    """A deck as page ranges, in order and without overlap.

    Contiguous rather than interleaved, so a chunk is a stretch of the deck the
    model can read as a narrative — and so the quote lookup in `_located` sees
    the neighbours a repeated header would appear on.

    An empty deck yields one empty call rather than none, deliberately: it keeps
    "the provider was asked and did not answer" distinguishable from "there was
    nothing to ask about", and the second is not a state this pipeline should
    reach in silence.
    """
    if not pages:
        return [pages]
    return [pages[start : start + size] for start in range(0, len(pages), size)]


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
