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
    claims, dropped = to_claims(answer())

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
    claims, dropped = to_claims(answer(figures=(), assertions=(ASSERTION,)))

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
    claims, _ = to_claims(answer(assertions=(ASSERTION,)))

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
    claims, _ = to_claims(answer(figures=({**FIGURE, "unit": "percentage"},)))

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
    claims, dropped = to_claims(answer(figures=(FIGURE, broken)))

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
    claims, dropped = to_claims(answer(figures=(), assertions=(ASSERTION, broken)))

    assert len(claims) == 1
    assert dropped == 1


def test_a_payload_is_not_mutated_by_being_read():
    """It is the caller's dict, and it is what gets inspected when this goes wrong.

    A reader that pops `page` out of each entry leaves the provider's reply
    subtly different from what arrived — and quietly breaks any second pass over
    the same payload.
    """
    payload = answer(assertions=(ASSERTION,))

    to_claims(payload)

    assert payload["figures"][0]["page"] == 3
    assert payload["assertions"][0]["page"] == 4


def test_an_answer_with_no_claims_is_empty_rather_than_an_error():
    """A title slide has no figures and no assertions, and that is not a failure.

    Most decks have several such pages. Treating "nothing here" as an error
    would fail materials for being ordinary.
    """
    assert to_claims(answer(figures=())) == ((), 0)


def test_a_missing_array_is_not_a_dropped_claim():
    """A deck of photographs legitimately has no figures on it.

    Counting an absent array as a drop would report damage on every extraction
    that simply found one kind and not the other — and the drop count is meant
    to be the signal that something went wrong.
    """
    assert to_claims({"assertions": [ASSERTION]})[1] == 0


def test_a_reply_shaped_nothing_like_the_tool_is_no_claims_and_no_crash():
    """Defensive, because this is parsing somebody else's output.

    An unhandled exception here runs inside the extraction sweep, where it marks
    nothing and leaves the material claimed until the requeue notices.
    """
    assert to_claims({}) == ((), 0)
    assert to_claims({"figures": "not a list", "assertions": None}) == ((), 0)


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
