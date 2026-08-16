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

from app.agents.archetypes import DEFAULT_PANEL, Archetype, by_name
from app.core.errors import ProviderUnavailable
from app.agents.panel import Asked, Grounding, TurnContext
from app.agents.panel_models import build_panel_model
from app.agents.panel_models.gemini import GeminiPanelModel
from app.core.config import Settings

CONTEXT = TurnContext(said="We hold 61% gross margin.", grounding=Grounding())

#: `_env_file=None` matters more than it looks. Without it `Settings` reads the
#: developer's real `backend/.env`, so the no-key test passes on a machine with no
#: Gemini key and fails on one that has it — a test whose result depends on who is
#: running it, which is worse than no test.
BASE_ENVIRONMENT = {
    "DATABASE_URL": "postgresql+asyncpg://user:pw@localhost:5432/flintroom",
    "JWT_SECRET": "x" * 48,
    "GOOGLE_CLIENT_ID": "297.apps.googleusercontent.com",
    "APPLE_CLIENT_ID": "com.flintroom.app",
    "_env_file": None,
}


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


async def test_an_archetype_is_told_only_what_it_has_asked_itself():
    """A flat "do not repeat" list steers a panelist off its own subject.

    By turn ten the CFO's prompt would carry six things not to repeat, all about
    margin — because margin is what the CFO asks about. That does not merely
    prevent repetition, it pushes the model away from the whole domain, and a CFO
    who stops asking about margin is worse than one who repeats himself.

    It is also the honest distinction. A panelist repeating himself is broken; two
    panelists circling the same number is a real room, and often the most
    uncomfortable part of one.
    """
    transport, seen = answering("And the payback period?")
    context = TurnContext(
        said="Margins are strong.",
        grounding=Grounding(
            asked=(
                Asked(archetype="cfo", question="What is your CAC payback?"),
                Asked(archetype="champion", question="Who is your reference customer?"),
            )
        ),
    )

    await model_with(transport).compose(archetype=by_name("cfo"), context=context)

    body = (seen[0]).content.decode()
    assert "What is your CAC payback?" in body
    assert "Who is your reference customer?" not in body


def test_the_configured_models_reach_the_adapter():
    """A setting nothing reads is a knob that does not turn.

    The realistic failure is the one this closes: somebody moves composition to a
    cheaper model on the evening the bill arrives, deploys, and nothing changes —
    because the builder was still passing the default. Both figures sit inside the
    §4.4 margins, since the panel runs on every turn of a metered session.
    """
    model = build_panel_model(
        Settings(
            **BASE_ENVIRONMENT,
            GEMINI_API_KEY="a-key-with-no-production-counterpart",
            PANEL_COMPOSITION_MODEL="gemini-3.6-flash",
        ),
        httpx.AsyncClient(),
    )

    assert model._composition_model == "gemini-3.6-flash"


def test_a_deployment_with_no_key_has_no_panel_rather_than_no_boot():
    """Absent, not fatal — the rule the voice provider and the bucket follow.

    A deployment without a panel key still signs people in, tracks balances and
    ingests decks. It cannot hold an interrogation, and refusing to boot would
    take everything else down with the one thing that is not ready.
    """
    assert build_panel_model(Settings(**BASE_ENVIRONMENT), httpx.AsyncClient()) is None


async def test_a_custom_archetype_routes_with_nothing_registered_anywhere():
    """The reason routing is a model call rather than a lookup table.

    A Pro user writes their own panelist this morning. It has no entry in any
    vocabulary, and keyword routing measured 53% relevance even for the
    archetypes it *does* know — so a custom one could never be chosen for
    relevance at all, only by having been quiet.

    The roster goes to the model as written, so a persona typed minutes ago is
    exactly as routable as one that shipped with the product.
    """
    transport, seen = answering("vc_partner")
    mine = Archetype(
        name="vc_partner",
        title="The Partner",
        persona="A partner who has seen four hundred decks this year.",
        attack_strategy="Attack the story. Why this, why you, why now.",
    )

    chosen = await model_with(transport).select(
        candidates=(*DEFAULT_PANEL, mine), context=CONTEXT
    )

    assert chosen == "vc_partner"
    assert "Attack the story" in seen[0].content.decode()


async def test_a_selection_answered_with_flourish_still_names_somebody():
    """`**cfo**`, `"cfo"` and `cfo.` are one answer and none of them match.

    Unhandled they reach the caller's fallback, so the room keeps running and
    quietly stops routing — which from outside is identical to a panel choosing
    at random.
    """
    transport, _ = answering('  "**cfo**."\n')

    chosen = await model_with(transport).select(
        candidates=DEFAULT_PANEL, context=CONTEXT
    )

    assert chosen == "cfo"
