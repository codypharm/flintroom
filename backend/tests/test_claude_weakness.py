"""Turning one vendor's reading of a room into judgements we can check.

The split every adapter in this codebase makes: everything Claude-shaped stops
in one module, and the interpretation — where the bugs that matter live — is
tested without a network or an account.

What is *not* tested here is whether the reading is any good. That is not a
property a mock can hold down, and `scripts/` is where it gets measured against
real rooms, the way #43 and #54 were. These tests hold the other half: that a
reply is turned into exactly what was said, that a malformed one is dropped
rather than believed, and that the room reaches the model with its notes on.
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
from app.agents.weakness_models.claude import ClaudeWeaknessReader
from app.modules.sessions.schemas import EndReason

pytestmark = pytest.mark.asyncio


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


def reader_with(handler) -> ClaudeWeaknessReader:
    """A real SDK client whose requests never leave the process."""
    return ClaudeWeaknessReader(
        api_key="test-key-with-no-production-counterpart",
        model="claude-sonnet-5",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def replying(weak: list[dict], *, usage: dict | None = None):
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
                        "id": "toolu_1",
                        "name": "report_weak_answers",
                        "input": {"weak": weak},
                    }
                ],
                "usage": usage or {"input_tokens": 1200, "output_tokens": 300},
            },
        )

    return handler


async def test_a_reading_comes_back_in_the_order_the_model_put_it_in():
    """The order *is* the ranking, and it belongs to the model.

    `Product.md` §3.5 asks for a ranked list, and this is where the rank is
    decided — with the whole room in view, by the only thing in the pipeline that
    read it. Nothing downstream re-sorts: `weak_answers` keeps what arrives,
    because a table of categories written before any room existed cannot outrank
    a judgement made after seeing one.

    So the assertion is on sequence, not on membership. An adapter that returned
    the right two judgements in the wrong order would be returning a different
    answer to the question that was asked.
    """
    reader = reader_with(
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


async def test_the_reader_satisfies_the_seam_it_is_plugged_into():
    """A guard, not a driver — and the reason `WeaknessReader` is runtime-checkable.

    There is no type checker in the suite, so renaming `rank` here would stay
    green in every test above and fail only when a debrief was opened. The
    failure would also be quiet in the worst way: a debrief that cannot call its
    reader finds nothing, and a session with nothing wrong in it is a legitimate
    result.
    """
    assert isinstance(reader_with(replying([])), WeaknessReader)


async def test_the_model_is_shown_the_room_numbered_and_annotated():
    """Everything the design rests on is in the prompt or is not happening.

    Two claims, and they fail differently. Without **numbers**, the model is
    being asked for ordinals it was never shown, so every quote check downstream
    fails and the debrief comes back empty. Without the **notes**, it works
    perfectly and is unfair: a question a colleague talked over reads as one the
    presenter ducked, which is the accusation #56 exists to prevent.

    Asserted on the bytes actually sent rather than on a helper, because a
    correct renderer wired to nothing looks the same from inside the adapter.
    """
    handler = replying([])
    await reader_with(handler).rank(room=annotate(ROOM, ended=EndReason.USER_ENDED))

    sent = json.loads(handler.request.content)["messages"][0]["content"]

    assert "[1] champion: Who inside the company will sponsor this?" in sent
    assert "[0] PRESENTER: Sponsorship is locked in for the year." in sent
    assert CUT_ACROSS in sent


async def test_a_room_the_model_found_nothing_wrong_with_is_not_an_error():
    """An empty reading is an answer, and once thinking is on it is a common one.

    A model that reasons and then declines to call the tool has said "nothing
    here was weak" in the only way the API offers. Treating a missing tool block
    as a failure would turn the best possible session into a broken debrief —
    and, worse, would make the failure rate depend on how well the user did.
    """
    reader = reader_with(
        lambda request: httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Nothing stood out."}],
                "usage": {"input_tokens": 900, "output_tokens": 40},
            },
        )
    )

    reading = await reader.rank(room=annotate(ROOM, ended=EndReason.USER_ENDED))

    assert reading.judged == ()
    assert reading.usage == TurnUsage(900, 40)
