"""Gemini, reading a finished room.

The second implementation of `WeaknessReader`, and the reason there are two:
`CLAUDE.md` puts the model layer behind an interface so a vendor can be swapped
on cost or availability, and an interface with one implementation has never been
shown to be one. This is Gemini's, written when the Anthropic account could not
be funded — which is the swap the seam exists for, arriving sooner than expected.

Same division as `test_claude_weakness.py`: everything Gemini-shaped is tested
here, and the parsing both vendors share is tested once, in
`test_weak_answers.py`, against the domain type rather than either envelope.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.agents.context import USER, Said
from app.agents.model import TurnUsage
from app.agents.weakness import (
    CUT_ACROSS,
    Judgement,
    Weakness,
    WeaknessReader,
    annotate,
)
from app.agents.weakness_models.gemini import GeminiWeaknessReader
from app.core.errors import ProviderUnavailable
from app.modules.sessions.schemas import EndReason


ROOM = (
    Said(speaker=USER, text="Sponsorship is locked in for the year."),
    Said(speaker="champion", text="Who inside the company will sponsor this?"),
    Said(
        speaker="cfo",
        text="The operational debt matters more. What does it cost to carry?",
        disputed=True,
    ),
    Said(speaker=USER, text="About two engineers full time."),
)


def reader_over(handler) -> GeminiWeaknessReader:
    return GeminiWeaknessReader(
        api_key="test-key-with-no-production-counterpart",
        model="gemini-3.7-flash",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def replying(weak: list[dict], *, usage: dict | None = None):
    """Gemini returns structured output as a JSON *string* in a text part."""

    def handler(request: httpx.Request) -> httpx.Response:
        handler.request = request
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": json.dumps({"weak": weak})}]}}
                ],
                "usageMetadata": usage
                or {"promptTokenCount": 1200, "candidatesTokenCount": 300},
            },
        )

    return handler


async def test_a_reading_comes_back_in_the_order_the_model_put_it_in():
    """The order is the ranking, and it survives the envelope.

    Gemini hands back structured output as a JSON string inside a text part
    rather than as a typed tool call, so there is one more layer here that can
    silently reorder or drop — `json.loads` on a string the model wrote, rather
    than a parsed object the SDK validated.
    """
    reader = reader_over(
        replying(
            [
                {
                    "ordinal": 1,
                    "quote": "Who inside the company will sponsor this?",
                    "weakness": "dismissed",
                    "why": "A colleague redirected the room before you answered.",
                },
                {
                    "ordinal": 2,
                    "quote": "What does it cost to carry?",
                    "weakness": "unsupported",
                    "why": "Two engineers is headcount, not a carrying cost.",
                },
            ]
        )
    )

    reading = await reader.rank(room=annotate(ROOM, ended=EndReason.USER_ENDED))

    assert reading.judged == (
        Judgement(
            ordinal=1,
            quote="Who inside the company will sponsor this?",
            weakness=Weakness.DISMISSED,
            why="A colleague redirected the room before you answered.",
        ),
        Judgement(
            ordinal=2,
            quote="What does it cost to carry?",
            weakness=Weakness.UNSUPPORTED,
            why="Two engineers is headcount, not a carrying cost.",
        ),
    )
    assert reading.usage == TurnUsage(1200, 300)


async def test_the_reader_satisfies_the_seam_it_is_plugged_into():
    """Two implementations, one seam, and this is what makes that claim real.

    `WeaknessReader` is runtime-checkable because there is no type checker here,
    so a reader that drifted off the seam would fail only when a debrief was
    opened — and fail quietly, since a debrief that finds nothing is a legitimate
    result for a session that went well.
    """
    assert isinstance(reader_over(replying([])), WeaknessReader)


async def test_the_model_is_shown_the_room_numbered_and_annotated():
    """The notes have to survive a second envelope, not just the first.

    Without numbers the model is asked for ordinals it was never shown, every
    quote check downstream fails, and the debrief comes back empty. Without the
    notes it works perfectly and is unfair — a question a colleague talked over
    reads as one the presenter ducked.

    Asserted on the bytes on the wire, because a correct renderer wired to
    nothing looks identical from inside the adapter.
    """
    handler = replying([])
    await reader_over(handler).rank(room=annotate(ROOM, ended=EndReason.USER_ENDED))

    sent = json.loads(handler.request.content)
    prompt = sent["contents"][0]["parts"][0]["text"]

    assert "[1] champion: Who inside the company will sponsor this?" in prompt
    assert "[0] PRESENTER: Sponsorship is locked in for the year." in prompt
    assert CUT_ACROSS in prompt


async def test_a_reply_that_is_not_json_at_all_is_survivable():
    """Structured output is a request, not a guarantee.

    A model that answers in prose despite a response schema — because it was
    refusing, or truncated mid-object — must cost the debrief its list, not the
    process. `json.loads` on that text raises, and an unhandled raise here is a
    500 on a phase the user was told is free.
    """
    reader = reader_over(
        lambda request: httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "The session went fine."}]}}
                ],
                "usageMetadata": {
                    "promptTokenCount": 900,
                    "candidatesTokenCount": 12,
                },
            },
        )
    )

    reading = await reader.rank(room=annotate(ROOM, ended=EndReason.USER_ENDED))

    assert reading.judged == ()
    # Still reported. The provider charged for the call whether or not we could
    # read the answer, and §4.3 reconciles against their invoice rather than
    # against what we managed to parse.
    assert reading.usage == TurnUsage(900, 12)


async def test_a_refusal_arrives_as_our_type_rather_than_the_vendors():
    """A 429 is our failure to report, not an `httpx` exception to leak.

    `ProviderUnavailable` is a 502 and deliberately does not name the vendor —
    `CLAUDE.md` forbids it, because it exposes internal architecture to whoever
    is probing and goes stale the moment the provider is swapped. Which is the
    swap that produced this file.
    """
    reader = reader_over(lambda request: httpx.Response(429, json={}))

    with pytest.raises(ProviderUnavailable):
        await reader.rank(room=annotate(ROOM, ended=EndReason.USER_ENDED))
