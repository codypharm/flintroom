"""Gemini holding the coaching conversation.

Everything Gemini-shaped is tested here; the fence itself is tested in
`test_coach.py` against the domain type, because it is the same fence whichever
vendor is behind it.

What only this file can get wrong is the prompt. The fence holds regardless —
an uncited turn becomes the redirect either way — but a prompt that never gets a
valid citation out of the model turns the coach into a redirect machine, which
is a broken product in the *other* direction and would look, from the outside,
exactly like the fence working. That is measured live in `scripts/coach.py`;
what is held down here is that the model is shown the things it is expected to
cite, numbered the way it must cite them.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.agents.coach import (
    COACH,
    Cite,
    CoachModel,
    Grounds,
    Spoken,
)
from app.agents.coach_models.gemini import GeminiCoachModel
from app.agents.context import USER, Said
from app.agents.model import TurnUsage
from app.agents.weakness import WeakAnswer, Weakness
from app.core.errors import ProviderUnavailable

GROUNDS = Grounds(
    transcript=(
        Said(speaker=USER, text="We grew forty percent last quarter."),
        Said(speaker="cfo", text="Off what base, and at what cost?"),
        Said(speaker=USER, text="We are really pleased with the trajectory."),
    ),
    weak_answers=(
        WeakAnswer(
            ordinal=1,
            question="Off what base, and at what cost?",
            asked_by="cfo",
            answer="We are really pleased with the trajectory.",
            weakness=Weakness.EVASIVE,
            why="You answered with a feeling about the trend, not a base.",
        ),
    ),
    claims=("Slide 4: gross margin held at 61% in Q3.",),
)

EXCHANGE = (Spoken(who=USER, text="Why did that one land badly?"),)


def coach_over(handler) -> GeminiCoachModel:
    return GeminiCoachModel(
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
                or {"promptTokenCount": 900, "candidatesTokenCount": 120},
            },
        )

    return handler


async def test_a_reply_comes_back_with_what_it_is_grounded_in():
    """The tracer: text and citations, typed, with what the call cost.

    `usage` travels for the reason it travels everywhere else here — the debrief
    is unmetered, not free, and §4.3 names the unmetered phases as the model's
    largest uncontrolled exposure. A coach that reported only words would leave
    a whole conversational phase invisible to the table that reconciles against
    an invoice.
    """
    coach = coach_over(
        replying(
            {
                "text": "The CFO asked for a base. You gave a mood. What was the number?",
                "cites": [{"kind": "line", "index": 1}],
            }
        )
    )

    reply = await coach.reply(grounds=GROUNDS, exchange=EXCHANGE)

    assert reply.text.startswith("The CFO asked for a base")
    assert reply.cites == (Cite(kind="line", index=1),)
    assert reply.usage == TurnUsage(900, 120)


async def test_the_model_is_shown_the_room_numbered_the_way_it_must_cite_it():
    """A citation is an index, so the indices have to be on the page.

    Without numbers the model is asked to cite ordinals it was never shown, so
    every citation fails the check and every turn becomes the redirect. The
    product would look scoped and be useless, and nothing would raise.

    The weak answers and the material go too — §405 names all three as the
    coach's grounding, and a coach that cannot see what the room got wrong
    cannot walk somebody through it.
    """
    handler = replying({"text": "", "cites": []})
    await coach_over(handler).reply(grounds=GROUNDS, exchange=EXCHANGE)

    prompt = json.loads(handler.request.content)["contents"][0]["parts"][0]["text"]

    assert "[1] cfo: Off what base, and at what cost?" in prompt
    assert "You answered with a feeling about the trend, not a base." in prompt
    assert "Slide 4: gross margin held at 61% in Q3." in prompt


async def test_the_conversation_so_far_goes_with_it():
    """§3.5 asks for a conversation, and a conversation has a memory.

    A coach that cannot see its own previous turn cannot be pushed back on,
    repeats itself, and answers a follow-up as though it were an opening
    question — which is the "static dashboard" §3.5 refuses, arriving through
    the back door.
    """
    handler = replying({"text": "", "cites": []})
    await coach_over(handler).reply(
        grounds=GROUNDS,
        exchange=(
            Spoken(who=COACH, text="You gave a mood rather than a base."),
            Spoken(who=USER, text="I did say we were growing, though."),
        ),
    )

    prompt = json.loads(handler.request.content)["contents"][0]["parts"][0]["text"]

    assert "You gave a mood rather than a base." in prompt
    assert "I did say we were growing, though." in prompt


async def test_a_malformed_citation_is_dropped_rather_than_believed():
    """One bad entry costs that entry, not the turn.

    But it does not cost *nothing*: a dropped citation may leave the turn with
    none, and `spoken` then replaces it with the redirect. That is the right
    outcome — a turn whose grounding could not be read is a turn nobody can
    check — and it is why this drops rather than coercing to some default index.
    """
    coach = coach_over(
        replying(
            {
                "text": "About that base.",
                "cites": [
                    {"kind": "line", "index": "one"},
                    {"kind": "elsewhere", "index": 0},
                    {"kind": "line", "index": 1},
                ],
            }
        )
    )

    reply = await coach.reply(grounds=GROUNDS, exchange=EXCHANGE)

    assert reply.cites == (Cite(kind="line", index=1),)


async def test_a_reply_that_is_not_json_leaves_the_turn_uncited():
    """Structured output is a request, not a guarantee.

    An unparseable reply must not raise out of a phase the user was told is
    free. Uncited is the safe landing: `spoken` turns it into the redirect, so
    the worst case is a coach that says "start a room" once, rather than a 500.
    """
    coach = coach_over(
        lambda request: httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "Sure — sounds good!"}]}}],
                "usageMetadata": {"promptTokenCount": 800, "candidatesTokenCount": 9},
            },
        )
    )

    reply = await coach.reply(grounds=GROUNDS, exchange=EXCHANGE)

    assert reply.cites == ()
    assert reply.usage == TurnUsage(800, 9)


async def test_a_refusal_arrives_as_our_type_rather_than_the_vendors():
    """`ProviderUnavailable`, without naming who was asked."""
    coach = coach_over(lambda request: httpx.Response(429, json={}))

    with pytest.raises(ProviderUnavailable) as refused:
        await coach.reply(grounds=GROUNDS, exchange=EXCHANGE)

    assert "gemini" not in str(refused.value.context).lower()


async def test_the_adapter_satisfies_the_seam_it_is_plugged_into():
    assert isinstance(coach_over(replying({"text": "", "cites": []})), CoachModel)
