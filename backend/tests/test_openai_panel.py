"""The OpenAI panel adapter, held to the Gemini adapter's own bar.

#13, with the architect's redirect recorded in the task: the comparison is
OpenAI against Gemini because Anthropic cannot take this account's payment —
a commercial fact, not a quality finding. Adding this adapter is a stack
change and the redirect is the approval, for the panel model only.

The prompts are imported from the incumbent, never copied: a paraphrase that
behaved differently from the text actually sent is exactly what a comparison
must be unable to hide. What these tests pin is the adapter shell — the same
properties `test_gemini_panel.py` pins for Google's.
"""

from __future__ import annotations

import httpx
import pytest

from app.agents.archetypes import DEFAULT_PANEL, by_name
from app.agents.context import Grounding, TurnContext
from app.agents.panel_models.openai import OpenAIPanelModel
from app.core.errors import ProviderUnavailable

CONTEXT = TurnContext(said="Margins are fine.", grounding=Grounding())


def replying(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def completion(text: str, *, prompt=11, completion_tokens=7):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion_tokens},
        },
    )


@pytest.mark.asyncio
async def test_composing_a_line_returns_what_the_model_wrote():
    async with replying(lambda request: completion("Off what base?")) as http:
        model = OpenAIPanelModel(api_key="sk-test", http=http)

        reply = await model.compose(archetype=by_name("cfo"), context=CONTEXT)

    assert reply.text == "Off what base?"
    assert reply.usage.input_tokens == 11
    assert reply.usage.output_tokens == 7


@pytest.mark.asyncio
async def test_a_selection_answered_with_flourish_still_names_somebody():
    async with replying(lambda request: completion('**cfo**.')) as http:
        model = OpenAIPanelModel(api_key="sk-test", http=http)

        reply = await model.select(candidates=DEFAULT_PANEL, context=CONTEXT)

    assert reply.text == "cfo"


@pytest.mark.asyncio
async def test_a_provider_failure_is_typed_and_does_not_name_the_vendor():
    async with replying(lambda request: httpx.Response(500, json={})) as http:
        model = OpenAIPanelModel(api_key="sk-test", http=http)

        with pytest.raises(ProviderUnavailable) as refused:
            await model.compose(archetype=by_name("cfo"), context=CONTEXT)

    assert "openai" not in str(refused.value).lower()
    assert "gpt" not in str(refused.value).lower()


@pytest.mark.asyncio
async def test_the_api_key_travels_in_a_header_and_never_the_url():
    seen: list[httpx.Request] = []

    def watch(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return completion("cfo")

    async with replying(watch) as http:
        model = OpenAIPanelModel(api_key="sk-test", http=http)
        await model.select(candidates=DEFAULT_PANEL, context=CONTEXT)

    assert seen, "no request left the adapter"
    assert "sk-test" not in str(seen[0].url)
    assert seen[0].headers["authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_selection_asks_for_the_cheapest_thinking_the_model_has():
    """gpt-5 models spend the completion budget on reasoning first, and a
    two-token routing answer starved by its own deliberation comes back
    empty. Selection pins reasoning to minimal; a room does not need the
    router to think, it needs it to answer while the presenter is still
    mid-sentence."""
    import json

    seen: list[httpx.Request] = []

    def watch(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return completion("cfo")

    async with replying(watch) as http:
        model = OpenAIPanelModel(api_key="sk-test", http=http)
        await model.select(candidates=DEFAULT_PANEL, context=CONTEXT)

    body = json.loads(seen[0].content)
    assert body["reasoning_effort"] == "minimal"
