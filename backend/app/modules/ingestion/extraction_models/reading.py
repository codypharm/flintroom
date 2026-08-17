"""What reading a deck means, with no vendor in it.

Everything here was written inside `claude.py` and moved out unchanged when a
second adapter arrived, which is the honest order: the shape of the shared part
is only knowable once two things need it. `docs/ingestion.md` and the interface
docstring both promised a second vendor would be a sibling module; this is the
half that promise turned out to depend on.

**What is vendor-shaped and stays out of here:** the content-block layout, the
tool or schema dialect, the client, the names of the fields a provider reports
usage under, and its exception types. What lives here is the job — what a page
is worth reading for, what a claim has to look like, where it is allowed to say
it came from, and what a half-read deck means.

The most important thing in this file is not code. `to_claims` and `_located`
carry the *"model extracts, code computes"* split `docs/auditor-grounding.md`
sets: the model says where it found a figure, and the text layer is searched to
find out whether that is true. Getting a second adapter for free is worth much
less than getting that rule applied identically by both.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.modules.ingestion.extraction_model import (
    ExtractedClaim,
    ExtractionResult,
    ExtractionUsage,
)
from app.modules.ingestion.parsing import RenderedPage, SlideChart
from app.modules.ingestion.schemas import ClaimKind

log = get_logger(__name__, tag="ingestion")


#: Statuses that mean *this request*, not *right now*. Retrying produces the
#: same refusal, so a deck that hits one is not worth requeueing — provided
#: something else in the same deck succeeded, which is the evidence that the
#: request shape itself is fine.
#:
#: Everything else — 429, 529, 5xx, timeouts, connection failures, and a
#: credential we got wrong — is a "come back later", because none of them are
#: anything the user's file did.
DECK_FATAL_STATUSES = frozenset({400, 413, 422})

INSTRUCTION = (
    "Each page is given as an image and its text layer. Read both: chart values "
    "are usually in the image only. Some pages also carry chart data read "
    "directly from the file that produced them — those numbers are exact, so "
    "where they disagree with what the image appears to show, use them. Record "
    "what the pages claim with the record_claims tool — figures in `figures`, "
    "non-numeric claims in `assertions`. Record exactly what is stated; never "
    "derive, convert, total, or infer a figure, and never soften an assertion."
)


@dataclass(frozen=True)
class Failed:
    """A call that gave up, and whether later could go differently.

    A record rather than `None`, because "it did not work" and "it will never
    work" are different answers and collapsing them is what turns a busy
    minute into somebody re-uploading a deck that was fine.
    """

    retryable: bool


def chunked(
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


def charts_as_text(charts: Sequence[SlideChart]) -> str:
    """Chart series as lines a model can read against the picture beside them.

    Rendered as text rather than handed over as JSON because it sits in the same
    message as the page image and the text layer, and one shape for all three is
    what stops the model treating this block as a different kind of question.

    A gap stays a gap and is written as such. `ChartSeries.values` is positional
    against `categories`, and the entire reason a missing value is carried rather
    than dropped is that dropping it would attach every later figure to the wrong
    period — so it must not be flattened away here either.
    """
    lines = []
    for chart in charts:
        lines.append(f"chart: {chart.title or '(untitled)'}")
        for series in chart.series:
            pairs = ", ".join(
                f"{category}={'no value' if value is None else value}"
                for category, value in zip(chart.categories, series.values, strict=False)
            )
            lines.append(f"  {series.name or '(unnamed series)'}: {pairs}")
    return "\n".join(lines)


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


def merged(
    readings: Sequence[ExtractionResult | Failed],
    *,
    pages: Sequence[RenderedPage],
    provider: str,
    model: str,
) -> ExtractionResult:
    """Every call's answer, as one deck's worth.

    An incomplete deck always drops its claims: a partially-read deck grounds
    less than the user believes, nothing downstream can tell, and the source is
    deleted on success — the gap would be permanent and invisible.

    What varies is whether it is worth trying again, and that is decided by
    *why* calls failed rather than by how many:

    - **A call the API refused outright** — 400, 413, 422. About this content,
      and retrying produces the same refusal forever. Not retryable, but only
      when some sibling chunk succeeded: that success is the evidence the
      request shape works. A malformed tool schema fails every call identically,
      and reading that as "this deck is unreadable" would permanently fail every
      deck uploaded while the bug was live.
    - **Anything else** — rate limits, timeouts, an overloaded provider, a
      credential we got wrong. Not the deck's fault, so the material waits and
      is tried again.

    It never raises. A caller that has to handle both a return value and an
    exception for the same question is one that will handle one of them wrong,
    and this is the seam a second vendor implements.

    `provider` and `model` are passed rather than read, because this is the one
    function here that has to name a vendor — in the usage row, where §4.3
    groups by it to reconcile against an invoice.
    """
    answered = [r for r in readings if isinstance(r, ExtractionResult)]
    failures = [r for r in readings if isinstance(r, Failed)]

    complete = not failures
    # Deny by default, applied to destroying somebody's deck: unretryable
    # requires both a permanent refusal *and* a sibling that worked. `all`, not
    # `any`: one permanent refusal outranks any number of transient ones,
    # because retrying cannot fix it and the deck would spin through the sweep
    # failing identically.
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

    # Counts only, never the claims. These are figures and statements read off a
    # confidential deck; CLAUDE.md forbids ingested material contents in logs,
    # and unlike a secret they are not detectable by key name.
    #
    # None of these is an error on its own. `corrected` is the attribution check
    # working, and the only measure of how far the model's own page numbers can
    # be trusted. `unverified` is how much of a deck is grounded in text nothing
    # could confirm — Open Risk #2 made countable rather than argued about.
    # `calls` is what task #31 added, and says whether the chunk size is set
    # anywhere near right once real decks have run through it.
    log.info(
        "extraction_completed",
        provider=provider,
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
            provider=provider,
            model=model,
            input_tokens=sum(r.usage.input_tokens for r in answered),
            output_tokens=sum(r.usage.output_tokens for r in answered),
            pages=len(pages),
            calls=len(readings),
        ),
    )
