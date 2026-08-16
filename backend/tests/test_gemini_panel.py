"""Gemini as a `PanelModel`.

No network. Every test drives a recorded transport, the same way
`test_claude_extraction.py` does — what is under test is the request we build and
the answer we take out of it, and neither needs a live endpoint or a funded
account to be wrong.

Gemini goes in first for a reason that is not architectural: it has a free tier
and the Anthropic account does not yet have credit, so this is the adapter that
can actually be measured. `docs/panel-orchestration.md` puts both behind one
interface precisely so the order costs nothing.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.agents.archetypes import DEFAULT_PANEL, by_name
from app.core.errors import ProviderUnavailable
from app.agents.panel import Grounding, TurnContext
from app.agents.panel_models.gemini import GeminiPanelModel

CONTEXT = TurnContext(said="We hold 61% gross margin.", grounding=Grounding())


def answering(text: str, *, status: int = 200):
    """A transport that returns one Gemini response, and remembers the request."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            status,
            json={
                "candidates": [
                    {"content": {"role": "model", "parts": [{"text": text}]},
                     "finishReason": "STOP"}
                ],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 7},
            },
        )

    return httpx.MockTransport(handler), seen


def model_with(transport) -> GeminiPanelModel:
    return GeminiPanelModel(
        api_key="a-key-with-no-production-counterpart",
        http=httpx.AsyncClient(transport=transport),
    )


async def test_composing_a_line_returns_what_the_model_wrote():
    """The tracer bullet: a request goes out, a panelist's line comes back."""
    transport, _ = answering("Where does 61% come from?")

    line = await model_with(transport).compose(
        archetype=by_name("cfo"), context=CONTEXT
    )

    assert line == "Where does 61% come from?"


async def test_the_composer_never_sees_the_rest_of_the_room():
    """The reason there are two calls instead of one.

    `docs/panel-orchestration.md` rejected a single prompt holding every persona
    because it averages them into one voice wearing four labels — a failure that
    reads perfectly well in a transcript and feels flat in a room, which is
    §3.3's "synthetic within two minutes".

    Asserted against the bytes actually sent, because this is exactly the thing a
    later refactor undoes while trying to save a call. Nothing else would catch
    it: the response still parses, the room still speaks, and the panel just
    quietly stops sounding like four people.
    """
    transport, seen = answering("Where does 61% come from?")

    await model_with(transport).compose(archetype=by_name("cfo"), context=CONTEXT)

    (request,) = seen
    body = request.content.decode()
    assert "The CFO" in body
    for other in DEFAULT_PANEL:
        if other.name != "cfo":
            assert other.title not in body
            assert other.attack_strategy not in body


async def test_a_provider_failure_is_typed_and_does_not_name_the_vendor():
    """`CLAUDE.md`: provider failures surface as `ProviderUnavailable` (502) and
    must not name the vendor.

    Two reasons, and the second is the one that bites. Naming it tells whoever is
    probing the endpoint what our architecture is — and it goes stale the moment
    the provider is swapped, which is a swap this whole interface exists to
    permit. A user reading "Gemini is unavailable" about a room that has since
    moved to Claude is worse than a user reading nothing.

    Untyped is worse still: an `httpx` error escaping here is a 500 with a
    traceback in the middle of a live metered room.
    """
    transport, _ = answering("", status=503)

    with pytest.raises(ProviderUnavailable) as failed:
        await model_with(transport).compose(archetype=by_name("cfo"), context=CONTEXT)

    said = failed.value.message.lower()
    assert "gemini" not in said
    assert "google" not in said


async def test_the_api_key_never_reaches_the_url():
    """Google documents a `key=` query parameter, and it is the wrong one.

    A URL is the part of a request that ends up in access logs, proxy logs and
    error trackers — none of which are places a credential should be recoverable
    from. `CLAUDE.md` allows zero secrets in logs, and a query parameter is a
    secret in every log by default.
    """
    transport, seen = answering("Where does 61% come from?")

    await model_with(transport).compose(archetype=by_name("cfo"), context=CONTEXT)

    (request,) = seen
    assert "a-key-with-no-production-counterpart" not in str(request.url)
    assert request.headers["x-goog-api-key"] == "a-key-with-no-production-counterpart"


async def test_the_deck_reaches_the_prompt_that_writes_the_challenge():
    """The wedge, at the wire.

    Every layer above this has been careful to carry the claims. If they stop at
    the adapter the whole chain is decoration — the panel would be grounded in
    everything except the request that actually asks for a question.
    """
    transport, seen = answering("Slide four says 61%.")
    grounded = TurnContext(
        said="Margins are strong.",
        grounding=Grounding(claims=("Gross margin of 61% in Q3 2026",)),
    )

    await model_with(transport).compose(archetype=by_name("cfo"), context=grounded)

    (request,) = seen
    assert "Gross margin of 61% in Q3 2026" in request.content.decode()


async def test_a_model_that_answers_with_flourish_still_names_somebody():
    """Selection returns a name, and a model returns prose.

    `**cfo**`, `"cfo"`, `cfo.` and a trailing newline are all the same answer and
    none of them match an archetype. Left unhandled they fall through to
    `_named`'s fallback, so the room keeps running and quietly stops routing —
    the panel would look like it was choosing at random, which is indistinguishable
    from a panel that is not listening.
    """
    transport, _ = answering('  "**cfo**."\n')

    chosen = await model_with(transport).select(
        candidates=DEFAULT_PANEL, context=CONTEXT
    )

    assert chosen == "cfo"
