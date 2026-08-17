"""Reading figures out of speech, over Gemini.

Everything vendor-shaped stops here: the URL, the header, the response schema,
where the JSON hides in the reply. Nothing above this module learns which
company is listening.

The same split as every other adapter in the project — translation is a pure
function tested exhaustively, the network is faked. What is under test is what
*we* decide: what the model is allowed to return, what happens to a room when it
returns rubbish, and what the call cost.

Nothing here reaches the real endpoint. What a live call would prove is latency
against Open Risk #3, and `docs/auditor-grounding.md` is explicit that this must
be measured when the layer lands rather than inferred — but that belongs to a
spike against a funded account, not to a suite that has to pass offline.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.agents.auditor import ClaimReader
from app.agents.claim_readers.gemini import GeminiClaimReader
from app.core.errors import ProviderUnavailable
from app.modules.ingestion.schemas import Unit

pytestmark = pytest.mark.asyncio


def reader_over(handler) -> tuple[GeminiClaimReader, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return GeminiClaimReader(api_key="secret", http=http), seen


def answering(payload: object, *, usage: dict | None = None):
    """A Gemini reply carrying `payload` as its JSON body."""
    body = {
        "candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}],
        "usageMetadata": usage or {"promptTokenCount": 120, "candidatesTokenCount": 30},
    }
    return lambda request: httpx.Response(200, json=body)


async def test_a_figure_in_speech_comes_back_typed_and_comparable():
    """The tracer bullet: an utterance in, something the Auditor can compare out.

    Unit and period are the load-bearing fields, not decoration.
    `docs/auditor-grounding.md` names comparability as the source of most false
    positives — last quarter's revenue against last year's is not a
    contradiction — and a claim that arrives without them is one the Auditor
    must either refuse or misuse.
    """
    reader, seen = reader_over(
        answering(
            {
                "claims": [
                    {
                        "quote": "our gross margin held at sixty-one percent last quarter",
                        "metric": "gross margin",
                        "value": 61,
                        "unit": "percent",
                        "period": "Q3 2026",
                    }
                ]
            }
        )
    )

    reading = await reader.read(
        said="Our gross margin held at sixty-one percent last quarter."
    )

    (claim,) = reading.claims
    assert claim.metric == "gross margin"
    assert claim.value == 61
    assert claim.unit is Unit.PERCENT
    assert claim.period == "Q3 2026"
    assert seen[0].headers["x-goog-api-key"] == "secret"


async def test_the_reader_satisfies_the_seam_it_is_plugged_into():
    """Structural typing gives no compile-time error when an adapter drifts.

    `ClaimReader` is a `Protocol`, so a renamed method or a changed keyword
    surfaces as an Auditor that silently never catches anything rather than as
    an import failure. Asserted here because the fake in `test_auditor.py`
    cannot notice — it conforms to the Protocol by construction, which is
    exactly how a fake and a real adapter drift apart.
    """
    reader, _ = reader_over(answering({"claims": []}))

    assert isinstance(reader, ClaimReader)


async def test_an_utterance_with_no_figure_in_it_is_the_ordinary_answer():
    """Most of what somebody says in an interrogation carries no number.

    Nothing to report is not a failure and must not read as one — an adapter
    that raised, or returned `None`, would make the commonest case the
    exceptional path and would put a try/except around every utterance.
    """
    reader, _ = reader_over(answering({"claims": []}))

    reading = await reader.read(said="I think we are in a strong position here.")

    assert reading.claims == ()


async def test_a_claim_the_model_malformed_is_dropped_rather_than_believed():
    """A model returns any shape it likes, and one bad entry must not cost the rest.

    The failure this prevents is specific and bad: a claim missing its unit, or
    carrying prose where a number belongs, reaching the comparison logic and
    being compared anyway. That is how a panelist ends up asserting, live and
    confidently, that a figure moved when it did not — the one failure
    `docs/auditor-grounding.md` says the grounding story cannot survive.

    Dropped rather than raised, because the good claims in the same utterance
    are still worth having, and because an interrogation must not end over a
    model's punctuation.
    """
    reader, _ = reader_over(
        answering(
            {
                "claims": [
                    {"metric": "revenue", "value": "one point two million",
                     "unit": "usd", "quote": "about one point two million"},
                    {"quote": "headcount is eleven", "metric": "headcount",
                     "value": 11, "unit": "count", "period": None},
                ]
            }
        )
    )

    reading = await reader.read(said="Revenue is about 1.2 million and we are eleven.")

    (claim,) = reading.claims
    assert claim.metric == "headcount"


async def test_a_reply_that_is_not_json_at_all_is_survivable():
    """Structured output is requested, not guaranteed.

    A model that answers with an apology, a code fence, or an empty string is a
    Tuesday. None of them are worth ending a metered room over, and the
    Auditor's caller treats "nothing found" as the ordinary case anyway.
    """
    reader, _ = reader_over(
        lambda request: httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "Sorry, I can't."}]}}]},
        )
    )

    assert (await reader.read(said="Our margin is seventy.")).claims == ()


async def test_a_refusal_arrives_as_our_type_rather_than_the_vendors():
    """The vendor's exception must not escape the adapter that speaks to it.

    Raised rather than swallowed, unlike the malformed cases above, and the
    distinction is deliberate: a model that answered badly is a bad answer, and
    a provider that refused is an outage. The Auditor swallows this one layer
    later — it is a background improvement to a working room — but the type has
    to arrive intact for that decision to be made where the trade is written
    down, and an `httpx.HTTPStatusError` reaching a caller would be a 500 rather
    than a refundable 502.

    **Deliberately does not assert that the message omits the vendor.**
    `ProviderUnavailable.message` is a class constant, so such an assertion
    passes no matter what this file does — it is green whether the guarantee
    holds or not. The real property is tested where it exists, against an actual
    response, in `test_error_handling.py`. Written this way after the mutation
    that put the vendor's name in `reason` survived the assertion that was here
    before.
    """
    reader, _ = reader_over(lambda request: httpx.Response(429, json={}))

    with pytest.raises(ProviderUnavailable):
        await reader.read(said="Anything.")


async def test_a_reading_reports_what_it_cost():
    """§4.3 reserves `auditor_invocations` because this runs per utterance.

    Which is materially more calls than the one-shot document diff the original
    costing assumed, and Open Risk #4 makes every per-minute figure
    load-bearing. Read off the provider's own report rather than counted here —
    reimplementing a vendor's tokeniser can only ever agree or be undetectably
    wrong.
    """
    reader, _ = reader_over(
        answering(
            {"claims": []},
            usage={"promptTokenCount": 240, "candidatesTokenCount": 12},
        )
    )

    reading = await reader.read(said="Our margin is seventy.")

    assert reading.usage.input_tokens == 240
    assert reading.usage.output_tokens == 12
