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

import json

import httpx
import pytest

from app.core.config import ConfigurationError, Settings
from app.core.errors import ProviderUnavailable
from app.modules.ingestion.extraction_model import ExtractionUsage
from app.modules.ingestion.extraction_models import build_extraction_model
from app.modules.ingestion.extraction_models.claude import (
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


async def test_a_provider_failure_never_names_the_vendor():
    """CLAUDE.md: `ProviderUnavailable` must not say who was unavailable.

    It exposes internal architecture and goes stale the moment the provider is
    swapped, which the interface exists to allow.
    """

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "anthropic exploded"}})

    with pytest.raises(ProviderUnavailable) as failure:
        await model_with(failing).extract([page(1)])

    assert "anthropic" not in failure.value.message.lower()
    assert "claude" not in failure.value.message.lower()


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
