"""Gemini reading a deck.

The second `ExtractionModel`, written when the Anthropic account could not be
funded — #61. The interpretation is not tested again here: `to_claims`,
`_located` and `merged` moved into `extraction_models/reading.py` unchanged and
are covered by `test_claude_extraction.py` against the same types both adapters
produce. Testing them twice would test the import.

What is tested here is what only this file can get wrong, and one item on that
list matters more than the rest.

**A page must be sent as image *and* text together.** `docs/ingestion.md` chose
a vision model for exactly this: `Product.md` §3.2 wants chart values per slide,
and a chart's numbers are in the pixels, not the text layer. An adapter that
sends only text is a working integration — it authenticates, returns claims,
passes every other test in this file — that silently loses every figure a deck
draws rather than writes. On a deck whose source document is deleted after a
successful extraction.
"""

from __future__ import annotations

import base64
import json

import httpx

from app.core.config import Settings
from app.modules.ingestion.extraction_models import build_extraction_model
from app.modules.ingestion.extraction_models.gemini import GeminiExtractionModel
from app.modules.ingestion.parsing import RenderedPage


BASE_ENVIRONMENT = {
    "DATABASE_URL": "postgresql+asyncpg://user:pw@localhost:5432/flintroom",
    "JWT_SECRET": "x" * 48,
    "GOOGLE_CLIENT_ID": "297.apps.googleusercontent.com",
    "APPLE_CLIENT_ID": "com.flintroom.app",
}

FIGURE = {
    "page": 1,
    "metric": "gross margin",
    "value": 61.0,
    "unit": "%",
    "period": "Q3 2026",
    "quote": "Gross margin held at 61% in Q3.",
}


def deck(*texts: str) -> tuple[RenderedPage, ...]:
    return tuple(
        RenderedPage(
            number=number,
            text=text,
            image=f"image-bytes-{number}".encode(),
            image_media_type="image/png",
        )
        for number, text in enumerate(texts, start=1)
    )


def model_with(handler) -> GeminiExtractionModel:
    return GeminiExtractionModel(
        api_key="test-key-with-no-production-counterpart",
        model="gemini-3.5-flash",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def replying(payload: dict, *, usage: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        handler.request = request
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": json.dumps(payload)}]}}
                ],
                "usageMetadata": usage
                or {"promptTokenCount": 2534, "candidatesTokenCount": 380},
            },
        )

    return handler


async def test_a_page_is_sent_as_image_and_text_together():
    """The property this vendor was chosen for, and the one that fails silently.

    A chart's values live in the pixels. An adapter sending only the text layer
    still authenticates, still returns claims, and still passes every other test
    here — while losing every figure the deck draws rather than writes. The
    source document is deleted once extraction succeeds, so that loss is
    permanent and nothing downstream can see it happened.

    Asserted on the bytes actually on the wire, in order, because the ordering is
    load-bearing too: the image goes first and the text reads as a caption for
    it. A model given them the other way round anchors on the text layer — which
    is the half missing the chart values.
    """
    handler = replying({"figures": [], "assertions": []})
    await model_with(handler).extract(deck("Gross margin held at 61% in Q3."))

    parts = json.loads(handler.request.content)["contents"][0]["parts"]
    kinds = [next(iter(part)) for part in parts]

    assert "inlineData" in kinds, "the page image never left the process"
    assert kinds.index("inlineData") < len(kinds) - 1, "the image must precede its text"

    image = next(part["inlineData"] for part in parts if "inlineData" in part)
    assert base64.b64decode(image["data"]) == b"image-bytes-1"
    assert image["mimeType"] == "image/png"

    assert any(
        "Gross margin held at 61% in Q3." in part.get("text", "") for part in parts
    ), "the text layer never left the process"


async def test_a_figure_comes_back_typed_and_placed():
    """The whole path, once, over a transport that never leaves the process.

    Not a test of `to_claims` — that lives in `reading.py` and is covered
    against the Claude adapter. This is the wiring: that the reply is found
    inside Gemini's envelope, handed to the shared parser, and returned as the
    type the seam promises.
    """
    model = model_with(replying({"figures": [FIGURE], "assertions": []}))

    result = await model.extract(deck("Gross margin held at 61% in Q3."))

    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.page == 1
    assert claim.claim.metric == "gross margin"
    assert claim.claim.value == 61.0
    # Found verbatim in the page's own text, so the citation was checked rather
    # than accepted — the distinction Open Risk #2 turns on.
    assert claim.quote_verified is True
    assert result.complete is True


async def test_an_extraction_reports_what_it_cost():
    """Extraction is a per-user cost with no revenue attached.

    The metering boundary is locked to live interrogation, so a deck that is
    read and never becomes a session is pure outflow — `docs/ingestion.md` names
    that as the abuse case. A vendor is named here because §4.3 groups by it,
    and the two adapters bill in different currencies at different rates.
    """
    model = model_with(replying({"figures": [FIGURE], "assertions": []}))

    usage = (await model.extract(deck("Gross margin held at 61% in Q3."))).usage

    assert usage.provider == "gemini"
    assert usage.model == "gemini-3.5-flash"
    assert usage.input_tokens == 2534
    assert usage.output_tokens == 380
    assert usage.pages == 1
    assert usage.calls == 1


async def test_a_deck_the_api_refuses_outright_is_not_retried_forever():
    """400 is about this file. Retrying produces the same refusal every sweep.

    Reported rather than raised, because a raise inside the extraction sweep
    marks nothing and leaves the material claimed until the requeue notices.

    `retryable` is true here despite the fatal status, and that is deliberate:
    nothing else in this deck succeeded, so there is no evidence the request
    shape works at all. A malformed schema fails every call identically, and
    reading that as "this deck is unreadable" would permanently destroy every
    deck uploaded while the bug was live.
    """
    model = model_with(lambda request: httpx.Response(400, json={}))

    result = await model.extract(deck("A page."))

    assert result.complete is False
    assert result.claims == ()
    assert result.retryable is True


async def test_a_reply_that_is_not_json_costs_the_claims_and_not_the_process():
    """Structured output is a request, not a guarantee.

    A model that answers in prose — refusing, or truncated mid-object — must not
    raise out of the sweep. The call is still on the invoice, so its usage is
    still reported.
    """
    model = model_with(
        lambda request: httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "No figures here."}]}}],
                "usageMetadata": {
                    "promptTokenCount": 2000,
                    "candidatesTokenCount": 5,
                },
            },
        )
    )

    result = await model.extract(deck("A page."))

    assert result.claims == ()
    assert result.complete is True
    assert result.usage.input_tokens == 2000


def test_the_configured_provider_is_the_one_built():
    """The default moved to Gemini in #61, and this is what says so.

    Also the guard on a subtler failure than a wrong class. The Gemini adapter
    borrows the application's `httpx` client rather than making its own — one
    connection pool per process, as the panel model does — so a builder that
    forgot to pass it would return `None` and produce a deployment that boots,
    accepts uploads, and grounds nothing. Which is the failure this whole task
    exists to have found once.
    """
    model = build_extraction_model(
        Settings(
            _env_file=None,
            **BASE_ENVIRONMENT,
            GEMINI_API_KEY="test-key-with-no-production-counterpart",
        ),
        http=httpx.AsyncClient(),
    )

    assert isinstance(model, GeminiExtractionModel)


def test_without_a_client_there_is_no_model_rather_than_a_broken_one():
    """Deny by default, applied to a half-built adapter.

    Returning a reader with no transport would fail on the first deck, inside
    the extraction sweep, where a raise marks nothing and leaves the material
    claimed until the requeue notices. `None` is the honest answer and it is
    logged at boot.
    """
    model = build_extraction_model(
        Settings(
            _env_file=None,
            **BASE_ENVIRONMENT,
            GEMINI_API_KEY="test-key-with-no-production-counterpart",
        )
    )

    assert model is None
