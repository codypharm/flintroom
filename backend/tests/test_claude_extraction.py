"""Turning one vendor's reply into typed claims.

The same split `test_elevenlabs_adapter.py` makes, for the same reason:
everything Claude-shaped stops in one module, and the interpretation — where the
bugs that matter live — is tested exhaustively without a network or an account.

What the transport tests below hold down is the one thing a mock cannot fake
later: that a page is sent as image *and* text together. `docs/ingestion.md`
chose this vendor precisely because it reads both, and sending only the text
would be a working integration that quietly loses every chart value.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

from app.core.config import ConfigurationError, Settings
from app.modules.ingestion.extraction_model import ExtractionUsage
from app.modules.ingestion.extraction_models import build_extraction_model
from app.modules.ingestion.extraction_models.claude import (
    DEFAULT_CONCURRENT_CALLS,
    ClaudeExtractionModel,
    to_claims,
)
from app.modules.ingestion.parsing import RenderedPage
from app.modules.ingestion.schemas import ClaimKind, Unit

BASE_ENVIRONMENT = {
    "DATABASE_URL": "postgresql+asyncpg://user:pw@localhost:5432/flintroom",
    "JWT_SECRET": "x" * 48,
    "GOOGLE_CLIENT_ID": "297.apps.googleusercontent.com",
    "APPLE_CLIENT_ID": "com.flintroom.app",
}

FIGURE = {
    "page": 3,
    "metric": "gross margin",
    "value": 61.0,
    "unit": "%",
    "period": "Q3 2026",
    "quote": "Gross margin held at 61% in Q3.",
}

ASSERTION = {
    "page": 4,
    "subject": "distribution",
    "statement": "Exclusive distribution agreement with Walmart.",
    "quote": "Exclusive distribution — Walmart, signed Q2.",
}


#: A deck of the given pages, numbered from one. Pass empty strings where a
#: test is not about the text layer.
def deck(*texts: str):
    return [
        RenderedPage(
            number=index + 1,
            text=text,
            image=b"\x89PNG not really",
            image_media_type="image/png",
        )
        for index, text in enumerate(texts)
    ]


def answer(figures=(FIGURE,), assertions=()) -> dict:
    return {"figures": list(figures), "assertions": list(assertions)}


def page(number: int = 1) -> RenderedPage:
    return RenderedPage(
        number=number,
        text=f"Slide {number}",
        image=b"\x89PNG not really",
        image_media_type="image/png",
    )


# --- Interpretation -------------------------------------------------------


def test_the_models_answer_becomes_typed_claims():
    """The tracer: a tool-use payload in, comparable claims out."""
    claims, dropped, _ = to_claims(answer(), pages=deck(*[''] * 4))

    assert dropped == 0
    assert len(claims) == 1
    assert claims[0].page == 3
    assert claims[0].claim.kind is ClaimKind.QUANTITATIVE
    assert claims[0].claim.metric == "gross margin"
    assert claims[0].claim.value == 61.0
    assert claims[0].claim.unit is Unit.PERCENT


def test_an_assertion_comes_back_as_its_own_kind():
    """The half of a deck that is not a number.

    `Product.md` asks the Auditor for *"contradictions, unsupported claims, and
    figures that moved"* — and exclusivity, patents and competitive absolutes
    are the sharpest things in most decks. Extracting only figures leaves the
    non-financial archetypes with nothing to attack.
    """
    claims, dropped, _ = to_claims(answer(figures=(), assertions=(ASSERTION,)), pages=deck(*[''] * 4))

    assert dropped == 0
    assert claims[0].page == 4
    assert claims[0].claim.kind is ClaimKind.ASSERTION
    assert claims[0].claim.subject == "distribution"
    assert claims[0].claim.statement.startswith("Exclusive distribution")


def test_both_kinds_come_back_from_one_call():
    """One model call reads a page for both, because it is looking anyway.

    Two calls would double the input tokens — the images are the expensive part
    — to answer two questions about the same pixels.
    """
    claims, _, _ = to_claims(answer(assertions=(ASSERTION,)), pages=deck(*[''] * 4))

    assert {claim.claim.kind for claim in claims} == {
        ClaimKind.QUANTITATIVE,
        ClaimKind.ASSERTION,
    }


def test_a_unit_the_model_invented_is_normalised_not_trusted():
    """The model writes prose; the closed set is decided here.

    Worth asserting at this boundary rather than only on the claim type, because
    this is the only place a model's output enters the type system — and a
    future adapter that built claims some other way would skip the validator.
    """
    claims, _, _ = to_claims(answer(figures=({**FIGURE, "unit": "percentage"},)), pages=deck(*[''] * 4))

    assert claims[0].claim.unit is Unit.PERCENT


@pytest.mark.parametrize(
    "broken",
    [
        {**FIGURE, "value": "1.2M"},
        {**FIGURE, "value": None},
        {**FIGURE, "metric": ""},
        {k: v for k, v in FIGURE.items() if k != "page"},
        {**FIGURE, "page": "three"},
        {**FIGURE, "page": 0},
    ],
)
def test_a_malformed_figure_is_dropped_rather_than_failing_the_page(broken):
    """One bad claim must not lose the forty good ones beside it.

    A model returns a list and gets one entry wrong; raising would discard an
    entire extraction that has already been paid for, and the material would
    fail for a reason no re-upload fixes. Dropping is the right call — but a
    silent drop is how a deck quietly grounds nothing, which is why the count
    comes back with the claims.
    """
    claims, dropped, _ = to_claims(answer(figures=(FIGURE, broken)), pages=deck(*[''] * 4))

    assert len(claims) == 1
    assert dropped == 1


@pytest.mark.parametrize(
    "broken",
    [
        {**ASSERTION, "statement": ""},
        {k: v for k, v in ASSERTION.items() if k != "subject"},
        {k: v for k, v in ASSERTION.items() if k != "quote"},
    ],
)
def test_a_malformed_assertion_is_dropped_too(broken):
    """The same rule on the other array.

    A missing quote matters more here than it looks: an assertion with nothing
    to cite is exactly the ungrounded challenge CLAUDE.md refuses to ship.
    """
    claims, dropped, _ = to_claims(answer(figures=(), assertions=(ASSERTION, broken)), pages=deck(*[''] * 4))

    assert len(claims) == 1
    assert dropped == 1


@pytest.mark.parametrize("cited", [4, 99])
def test_a_claim_citing_a_page_that_does_not_exist_is_dropped(cited):
    """The page is what the panel says out loud, so it has to be real.

    The number is *reported by the model*, not attached structurally — it reads
    "Page 2 text layer:" and writes back which page a figure was on. Nothing
    else checks it, so a two-page deck can come back with a claim on page 99,
    and the failure surfaces as a panelist demanding the user defend page 99 of
    a two-page deck. One line, and the room's credibility is gone.

    Dropped rather than clamped or kept pageless. A citation that has been
    guessed at is worse than a missing claim, and CLAUDE.md is explicit: do not
    ship interrogation logic that cannot cite its source.
    """
    claims, dropped, _ = to_claims(
        answer(figures=(FIGURE, {**FIGURE, "page": cited})), pages=deck(*[''] * 3)
    )

    assert dropped == 1
    assert [claim.page for claim in claims] == [3]


def test_the_last_page_of_a_deck_is_a_page_that_exists():
    """The boundary the check above is drawn at, asserted from the other side.

    An off-by-one here silently drops every claim on a deck's final slide, which
    is usually the ask — the single most attackable page in a pitch.
    """
    claims, dropped, _ = to_claims(answer(figures=({**FIGURE, "page": 3},)), pages=deck(*[''] * 3))

    assert dropped == 0
    assert claims[0].page == 3


# --- Attribution ----------------------------------------------------------
#
# The page a claim carries is *reported by the model*: it reads "Page 2 text
# layer:" and writes back where it found something. The range check above only
# refuses a page that does not exist — page 99 of a four-page deck. It says
# nothing about page 4 labelled page 3, which is the mistake far more likely to
# happen and the one nobody would notice.
#
# The quote is what makes that checkable without a model. If the source text is
# in a page's text layer, code can find which page that actually is.


def test_a_misattributed_claim_is_moved_to_the_page_its_quote_is_on():
    """Attribution corrected by search, not by trusting the answer.

    Where the source text is in a text layer, which page it is on is a fact
    about the deck rather than an opinion of the model's — so it is looked up.
    Exactly the *"model extracts, code computes"* split, applied to the locator
    instead of to arithmetic.
    """
    pages = deck(
        "Title slide",
        "Gross margin held at 61% in Q3.",
        "Thank you",
    )

    claims, dropped, corrected = to_claims(
        answer(figures=({**FIGURE, "page": 3},)), pages=pages
    )

    assert dropped == 0
    assert corrected == 1
    assert claims[0].page == 2


def test_a_claim_already_on_the_right_page_is_left_alone():
    """The common case, and it must not be counted as a correction.

    `corrected` is the signal for how far the model's attribution can be
    trusted, so inflating it would hide the answer to that question.
    """
    pages = deck("Title", "Gross margin held at 61% in Q3.")

    claims, _, corrected = to_claims(
        answer(figures=({**FIGURE, "page": 2},)), pages=pages
    )

    assert corrected == 0
    assert claims[0].page == 2


def test_a_chart_value_keeps_the_page_the_model_reported():
    """The limit of this technique, asserted rather than left implicit.

    A figure read off a chart is in the pixels and appears in no text layer, so
    there is nothing to search for. Those claims stay best-effort — which is
    precisely the half `pypdf` alone would have missed, and the reason a vision
    model is here at all.
    """
    pages = deck("Title slide", "Revenue", "Thank you")

    claims, dropped, corrected = to_claims(
        answer(figures=({**FIGURE, "page": 2},)), pages=pages
    )

    assert (dropped, corrected) == (0, 0)
    assert claims[0].page == 2


def test_a_quote_that_appears_on_several_pages_is_not_moved():
    """A running header or a repeated summary line is on every slide.

    Ambiguous evidence must not override the model, which at least looked at the
    images. Correcting to the first match would be inventing a citation with the
    confidence of a lookup.
    """
    repeated = "Gross margin held at 61% in Q3."
    pages = deck(repeated, repeated, repeated)

    claims, _, corrected = to_claims(
        answer(figures=({**FIGURE, "page": 3},)), pages=pages
    )

    assert corrected == 0
    assert claims[0].page == 3


def test_attribution_survives_the_whitespace_a_pdf_puts_in():
    """Extracted text breaks lines wherever the layout did.

    A quote the model tidied into one line would otherwise match nothing, and
    the check would silently do nothing on real decks while passing every test
    written with clean strings.
    """
    pages = deck("Title", "Gross margin held\nat 61%   in Q3.")

    claims, _, corrected = to_claims(
        answer(figures=({**FIGURE, "page": 1},)), pages=pages
    )

    assert corrected == 1
    assert claims[0].page == 2


def test_a_quote_found_in_the_deck_is_marked_verified():
    """One bit saying "these are really the deck's words".

    Open Risk #2 is that ungrounded questions kill retention, and CLAUDE.md
    refuses interrogation logic that cannot cite its source. This is the
    difference between a citation that was checked and one that was accepted —
    and it costs nothing, because the search that answers it already runs for
    attribution.
    """
    pages = deck("Title", "Gross margin held at 61% in Q3.")

    claims, _, _ = to_claims(answer(figures=({**FIGURE, "page": 2},)), pages=pages)

    assert claims[0].quote_verified is True


def test_a_chart_value_is_marked_unverified():
    """The claims nothing can check, made visible instead of silently mixed in.

    A figure read off a chart is in the pixels and appears in no text layer, so
    neither its wording nor its page can be confirmed. Those are also exactly
    the figures a CFO archetype would attack hardest — so the panel should be
    able to tell them apart when choosing what to press on.
    """
    pages = deck("Title", "Revenue by quarter")

    claims, _, _ = to_claims(answer(figures=({**FIGURE, "page": 2},)), pages=pages)

    assert claims[0].quote_verified is False


def test_a_quote_on_several_pages_is_still_the_decks_words():
    """Verification and attribution are different questions.

    A running header appears on every slide: *which* page it came from is
    genuinely ambiguous, but that the deck says it is not in doubt. Marking it
    unverified would throw away a fact we have, over one we do not.
    """
    repeated = "Gross margin held at 61% in Q3."
    pages = deck(repeated, repeated, repeated)

    claims, _, corrected = to_claims(
        answer(figures=({**FIGURE, "page": 3},)), pages=pages
    )

    assert claims[0].quote_verified is True
    assert (claims[0].page, corrected) == (3, 0)


def test_an_assertion_is_verified_the_same_way():
    """Both kinds, because both are spoken and both need to cite something."""
    pages = deck("Title", "Exclusive distribution — Walmart, signed Q2.")

    claims, _, _ = to_claims(
        answer(figures=(), assertions=({**ASSERTION, "page": 2},)), pages=pages
    )

    assert claims[0].quote_verified is True


def test_verification_is_off_unless_something_checked_it():
    """The default has to be the unproven one.

    A flag defaulting to True is a future adapter — or a hand-built fixture —
    silently asserting that a citation was confirmed when nothing looked.
    """
    from app.modules.ingestion.extraction_model import ExtractedClaim

    fields = {k: v for k, v in FIGURE.items() if k != "page"}
    built = ExtractedClaim(page=1, claim={**fields, "kind": "quantitative"})

    assert built.quote_verified is False


def test_a_payload_is_not_mutated_by_being_read():
    """It is the caller's dict, and it is what gets inspected when this goes wrong.

    A reader that pops `page` out of each entry leaves the provider's reply
    subtly different from what arrived — and quietly breaks any second pass over
    the same payload.
    """
    payload = answer(assertions=(ASSERTION,))

    to_claims(payload, pages=deck(*[''] * 4))

    assert payload["figures"][0]["page"] == 3
    assert payload["assertions"][0]["page"] == 4


def test_an_answer_with_no_claims_is_empty_rather_than_an_error():
    """A title slide has no figures and no assertions, and that is not a failure.

    Most decks have several such pages. Treating "nothing here" as an error
    would fail materials for being ordinary.
    """
    assert to_claims(answer(figures=()), pages=deck(*[''] * 4)) == ((), 0, 0)


def test_a_missing_array_is_not_a_dropped_claim():
    """A deck of photographs legitimately has no figures on it.

    Counting an absent array as a drop would report damage on every extraction
    that simply found one kind and not the other — and the drop count is meant
    to be the signal that something went wrong.
    """
    assert to_claims({"assertions": [ASSERTION]}, pages=deck(*[''] * 4))[1] == 0


def test_a_reply_shaped_nothing_like_the_tool_is_no_claims_and_no_crash():
    """Defensive, because this is parsing somebody else's output.

    An unhandled exception here runs inside the extraction sweep, where it marks
    nothing and leaves the material claimed until the requeue notices.
    """
    assert to_claims({}, pages=deck(*[''] * 4)) == ((), 0, 0)
    assert to_claims({"figures": "not a list", "assertions": None}, pages=deck(*[''] * 4)) == ((), 0, 0)


# --- Transport ------------------------------------------------------------


def model_with(handler) -> ClaudeExtractionModel:
    """A real SDK client whose requests never leave the process."""
    return ClaudeExtractionModel(
        api_key="test-key-with-no-production-counterpart",
        model="claude-sonnet-5",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def replying(payload: dict, *, usage: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        handler.request = request
        return httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5",
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "record_claims",
                        "input": payload,
                    }
                ],
                "usage": usage or {"input_tokens": 1200, "output_tokens": 340},
            },
        )

    return handler


async def test_a_page_is_sent_as_image_and_text_together():
    """The reason this vendor was chosen, asserted on the wire.

    Chart data is not in a text layer — `pypdf` returns a chart's axis labels
    and none of its values — so a request carrying only text is an integration
    that works, passes, and silently loses every figure the deck draws rather
    than writes.
    """
    handler = replying(answer())

    await model_with(handler).extract([page(1), page(2)])

    content = json.loads(handler.request.content)["messages"][0]["content"]
    kinds = [block["type"] for block in content]

    assert kinds.count("image") == 2
    assert kinds.count("text") >= 2


async def test_usage_comes_back_so_the_extraction_can_be_costed():
    """CLAUDE.md: cost instrumentation is a required task, not a later addition.

    Extraction is unmetered cost with no revenue attached — the metering
    boundary is locked to live interrogation — so the abuse case is a deck
    extracted and never turned into a session. An interface that returned only
    claims would make that invisible and force re-plumbing when
    `extraction_costs` lands.
    """
    handler = replying(
        answer(), usage={"input_tokens": 4096, "output_tokens": 512}
    )

    result = await model_with(handler).extract([page(1)])

    assert result.usage == ExtractionUsage(
        provider="claude",
        model="claude-sonnet-5",
        input_tokens=4096,
        output_tokens=512,
        pages=1,
    )


async def test_a_provider_failure_reaches_no_client_at_all(caplog):
    """CLAUDE.md: a provider failure must not name the vendor to the client.

    Extraction now satisfies that by having nothing to say to a client: it
    returns an incomplete result rather than raising, so a failed read surfaces
    as a material that is still `pending` and never as an error carrying a
    message. Strictly safer than a carefully worded one.

    Rewritten when `extract` stopped raising (the classifier). The rule did not
    change; the surface it applied to disappeared. What survives is the other
    half — the vendor is named in the log, where it belongs and where a client
    cannot read it.
    """

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"message": "anthropic exploded"}}
        )

    with caplog.at_level(logging.ERROR):
        result = await model_with(failing).extract([page(1)])

    assert result.complete is False
    assert any(
        getattr(record, "context", {}).get("provider") == "claude"
        for record in caplog.records
    )


# --- Wiring ---------------------------------------------------------------


def test_no_extraction_model_without_credentials():
    """Same trade as the voice provider and the bucket.

    A missing extraction key is an unconfigured integration, not an insecure
    default: auth, balances and the voice loop all work without it, and
    `docs/auditor-grounding.md` makes the deckless path first-class rather than
    degraded. Refusing to boot would take working routers down with it.
    """
    assert build_extraction_model(Settings(_env_file=None, **BASE_ENVIRONMENT)) is None


def test_the_configured_provider_is_the_one_built():
    """The single place that decides which vendor is in use."""
    model = build_extraction_model(
        Settings(
            _env_file=None,
            **BASE_ENVIRONMENT,
            ANTHROPIC_API_KEY="test-key-with-no-production-counterpart",
        )
    )

    assert isinstance(model, ClaudeExtractionModel)


def test_a_provider_nobody_implemented_is_a_boot_refusal():
    """A typo must not become "extraction is quietly off".

    The failure this prevents is the worst kind: a deployment that starts, signs
    people in, accepts uploads, and never grounds a single session — because
    `EXTRACTION_PROVIDER=cluade` silently meant "none".
    """
    with pytest.raises(ConfigurationError):
        Settings(
            _env_file=None,
            **BASE_ENVIRONMENT,
            ANTHROPIC_API_KEY="key",
            EXTRACTION_PROVIDER="cluade",
        )


# --- Chunking -------------------------------------------------------------


def recording(payload: dict, *, usage: dict | None = None):
    """A handler that keeps every request, not only the last.

    Chunking is invisible in a single request, which is exactly why the bug it
    replaces went unnoticed: a deck too long for the context failed at the
    provider, identically, forever.
    """
    reply = replying(payload, usage=usage)

    def handler(request: httpx.Request) -> httpx.Response:
        handler.requests.append(request)
        return reply(request)

    handler.requests = []
    return handler


def pages_in(request: httpx.Request) -> list[int]:
    """Which pages a request carried, read off the wire."""
    content = json.loads(request.content)["messages"][0]["content"]
    return [
        int(block["text"].split()[1])
        for block in content
        if block["type"] == "text" and block["text"].startswith("Page ")
    ]


async def test_a_deck_too_long_for_one_call_is_read_in_several():
    """The tracer, and the reason this task exists.

    A rendered page is ~2,000-2,500 input tokens, so a full pro-tier deck is
    around 600k against a 200k context. Unchunked it does not fail gracefully:
    it fails at the provider, identically, on every sweep.
    """
    handler = recording(answer(figures=()))

    await model_with(handler).extract([page(n) for n in range(1, 46)])

    assert len(handler.requests) == 3


async def test_every_page_is_read_exactly_once():
    """Chunking must not lose or duplicate a page.

    A dropped page is a claim the panel never has and cannot know it is
    missing; a duplicated one is the same figure twice, which reads to the
    Auditor as a deck agreeing with itself.
    """
    handler = recording(answer(figures=()))

    await model_with(handler).extract([page(n) for n in range(1, 46)])

    seen = [number for request in handler.requests for number in pages_in(request)]
    assert sorted(seen) == list(range(1, 46))


async def test_a_chunk_is_a_contiguous_stretch_of_the_deck():
    """Contiguous, not interleaved.

    A chunk should read as a stretch of the deck's argument, and the quote
    lookup should see the neighbouring pages a repeated header would appear on.
    """
    handler = recording(answer(figures=()))

    await model_with(handler).extract([page(n) for n in range(1, 46)])

    ranges = sorted(pages_in(request) for request in handler.requests)
    assert ranges == [
        list(range(1, 21)),
        list(range(21, 41)),
        list(range(41, 46)),
    ]


async def test_a_deck_that_fits_is_still_one_call():
    """The common case pays nothing for the long one.

    Most attached material is a photograph or a twelve-slide deck, and splitting
    those would repeat the instruction block for no reason.
    """
    handler = recording(answer(figures=()))

    await model_with(handler).extract([page(n) for n in range(1, 13)])

    assert len(handler.requests) == 1


async def test_claims_from_every_call_come_back_as_one_deck():
    """Chunking stops inside the adapter.

    Nothing above this learns that a deck became several requests — which is
    what lets a vendor with a larger context be a sibling module rather than a
    change to the pipeline.
    """
    handler = recording(answer(figures=({**FIGURE, "page": 1},)))

    result = await model_with(handler).extract([page(n) for n in range(1, 46)])

    assert len(handler.requests) == 3
    assert result.usage.calls == 3
    assert result.complete is True
    # Page 1 is only in the first chunk, so the other two calls answer with a
    # claim citing a page they were not given — and `to_claims` drops it. That
    # is the range check doing its job, not a chunking bug.
    assert len(result.claims) == 1


def refusing(
    first_pages: set[int],
    payload: dict,
    *,
    usage: dict | None = None,
    status: int = 400,
):
    """A handler that fails the calls starting at the given pages.

    400 by default so the SDK does not retry — most of these tests are about
    what happens once a call has genuinely given up, not about the retry itself.
    `retry-after: 0` keeps the retryable statuses instant.
    """
    reply = replying(payload, usage=usage)

    def handler(request: httpx.Request) -> httpx.Response:
        handler.requests.append(request)
        if pages_in(request)[0] in first_pages:
            return httpx.Response(
                status,
                headers={"retry-after": "0"},
                json={
                    "type": "error",
                    "error": {"type": "invalid_request_error", "message": "no"},
                },
            )
        return reply(request)

    handler.requests = []
    return handler


async def test_one_failed_call_discards_the_whole_deck():
    """Fail whole, not partial — the decision behind task #31.

    A partially-read deck grounds less than the user believes, nothing
    downstream can tell the difference, and the source document is deleted on
    success. The gap would be permanent and invisible, which is why
    `docs/ingestion.md` calls extraction completeness *"a one-way door, not a
    backlog item."*
    """
    handler = refusing({21}, answer(figures=({**FIGURE, "page": 1},)))

    result = await model_with(handler).extract([page(n) for n in range(1, 46)])

    assert result.complete is False
    assert result.claims == ()


async def test_a_failed_deck_still_reports_what_it_cost():
    """The reason this returns rather than raises.

    Those calls are on the invoice whether or not their answers were usable, and
    cost that cannot be reconciled is worse than cost that was wasted —
    §4.3 measures margin against observed spend, not against spend that
    succeeded.
    """
    handler = refusing(
        {21},
        answer(figures=()),
        usage={"input_tokens": 40_000, "output_tokens": 2_000},
    )

    result = await model_with(handler).extract([page(n) for n in range(1, 46)])

    assert result.usage.calls == 3
    assert result.usage.pages == 45
    # Two calls answered, and only those two were billed for tokens.
    assert result.usage.input_tokens == 80_000
    assert result.usage.output_tokens == 4_000


async def test_a_deck_nothing_answered_records_no_spend():
    """A refusal before any answer costs nothing, so it records nothing.

    `docs/ingestion.md`: *"`extraction_costs` records work performed; a material
    refused before a model call has no row."* The same holds for calls that were
    made and refused — nothing was billed, so an empty usage keeps the cost
    table free of rows that describe no work.
    """
    handler = refusing({1, 21, 41}, answer(figures=()))

    result = await model_with(handler).extract([page(n) for n in range(1, 46)])

    assert result.usage.input_tokens == 0
    assert result.usage.output_tokens == 0


async def test_calls_run_in_parallel_but_not_all_at_once():
    """Bounded, in both directions.

    Sequentially, fifteen calls is minutes of wall clock for somebody who
    uploaded a deck in order to rehearse against it now. Unbounded, one
    enthusiastic user spends an account-wide rate limit — and the failure that
    causes is a 429 on every other deck being read at the same time.
    """
    inflight = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal inflight
        inflight += 1
        handler.peak = max(handler.peak, inflight)
        # Yield, so an overlapping call has somewhere to be scheduled. Without
        # it every request would finish before the next began and the test would
        # pass against a sequential loop.
        await asyncio.sleep(0.01)
        inflight -= 1
        return replying(answer(figures=()))(request)

    handler.peak = 0

    await model_with(handler).extract([page(n) for n in range(1, 201)])

    assert handler.peak == DEFAULT_CONCURRENT_CALLS


async def test_a_transient_failure_is_retried_before_the_deck_is_lost():
    """Retries are configured here, not inherited.

    The SDK retries twice by default; this asks for four, because one chunk that
    gives up discards every other chunk's claims. A transient overload on call
    eight of fifteen would otherwise throw away fourteen calls that were already
    paid for.

    `retry-after: 0` keeps the test instant — the backoff is the SDK's and not
    what is being asserted. What is asserted is that a call which fails twice
    still produces a read deck.
    """
    reply = replying(answer(figures=()))
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            return httpx.Response(
                429,
                headers={"retry-after": "0"},
                json={
                    "type": "error",
                    "error": {"type": "rate_limit_error", "message": "slow down"},
                },
            )
        return reply(request)

    result = await model_with(handler).extract([page(1)])

    assert attempts == 3
    assert result.complete is True


# --- Whose fault was it -----------------------------------------------------


async def test_a_rate_limited_deck_says_it_is_worth_trying_again():
    """A 429 is not the deck's fault, and must not be treated as one.

    Under load, retries exhaust *unevenly* — some chunks land, some do not — so
    a partial failure is the likely shape of a rate-limit event rather than a
    rare one. Marking the material `failed` there would tell the user to
    re-upload a deck that was never the problem, turning a capacity problem into
    data loss.
    """
    handler = refusing({21}, answer(figures=()), status=429)

    result = await model_with(handler).extract([page(n) for n in range(1, 46)])

    assert result.complete is False
    assert result.retryable is True


async def test_a_deck_the_api_refuses_outright_is_not_worth_retrying():
    """A 400 is about this content, and trying again produces the same 400.

    Left retryable it would spin through the sweep forever, failing identically
    and burning a claim every pass — the failure `docs/ingestion.md` already
    names for the per-file page cap.
    """
    handler = refusing({21}, answer(figures=()))

    result = await model_with(handler).extract([page(n) for n in range(1, 46)])

    assert result.complete is False
    assert result.retryable is False


async def test_a_deck_is_never_failed_without_evidence_the_request_works():
    """Nothing answered means we have no reason to blame the deck.

    A malformed tool schema or a bad model name is a 400 on *every* call, and
    reading that as "this deck is unreadable" would permanently fail every deck
    uploaded while the bug was live. A sibling chunk succeeding is the evidence
    that the request shape is fine and the content is not — without it, the
    honest answer is that we do not know.
    """
    handler = refusing({1, 21, 41}, answer(figures=()))

    result = await model_with(handler).extract([page(n) for n in range(1, 46)])

    assert result.complete is False
    assert result.retryable is True


async def test_a_permanent_failure_outranks_a_transient_one():
    """Retrying cannot fix the 400, so the deck is not worth requeueing for it."""
    handler = refusing({21}, answer(figures=()))
    rate_limited = refusing({41}, answer(figures=()), status=429)

    def both(request: httpx.Request) -> httpx.Response:
        if pages_in(request)[0] == 41:
            return rate_limited(request)
        return handler(request)

    result = await model_with(both).extract([page(n) for n in range(1, 46)])

    assert result.complete is False
    assert result.retryable is False


async def test_a_whole_deck_that_was_read_is_not_retryable():
    """`retryable` is only a question once something went wrong."""
    handler = recording(answer(figures=()))

    result = await model_with(handler).extract([page(1)])

    assert result.complete is True
    assert result.retryable is False


def test_the_configured_concurrency_reaches_the_model():
    """A setting nothing reads is a knob that does not turn.

    The realistic failure is the one this closes: somebody lowers
    `EXTRACTION_CONCURRENT_CALLS` on the evening it starts rate-limiting,
    deploys, and nothing changes — because the builder was still passing the
    default.
    """
    model = build_extraction_model(
        Settings(
            **BASE_ENVIRONMENT,
            ANTHROPIC_API_KEY="test-key-with-no-production-counterpart",
            EXTRACTION_CONCURRENT_CALLS=2,
        )
    )

    assert model._concurrent_calls == 2
