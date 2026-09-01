"""Claude, as a `WeaknessReader`.

Everything vendor-shaped stops here: the tool schema, the content-block layout,
`tool_use`, extended thinking. A second vendor is a sibling of this file.

**A reasoning model, deliberately, and against the measured precedent.** The same
comparison run for panel composition went the other way — `config.py` records
0.82s against 2.11s, and a *sharper* line from the cheap model, because a
panelist says one short hostile thing and a reasoning model writes a considered
paragraph. Nothing about that result transfers here, and the reason is the job
rather than the vendor:

- **There is no clock.** One call, once, after the room has closed. Open Risk #3
  governs everything inside a session and nothing here.
- **The thing being bought is exactly what thinking is for.** This exists to
  catch a fluent, specific, confidently *wrong* answer — the one no rule in code
  can see. A model reading fast is the model that misses it.
- **Once per session, not once per turn.** Panel composition sits inside the
  §4.4 margins that Open Risk #4 already flags. This does not; it is a few
  thousand input tokens against a room that cost ~$0.48 to hold.

The prompt asks for a reading and never for a rule to be applied. #43 measured
what happens to a rule handed to a model — asked whether the presenter had
dodged, it said yes on 4 of 4 dodges *and* 4 of 4 genuine answers. What replaced
that is not a better-worded rule; it is a forced ranking, a required quote, and
`weakness.verified` checking the quote afterwards.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, ToolParam

from app.agents.model import TurnUsage
from app.agents.weakness import (
    INSTRUCTION,
    Annotated,
    Strength,
    Weakness,
    WeaknessReading,
    render,
    to_judgements,
    to_strengths,
)
from app.core.logging import get_logger

log = get_logger(__name__, tag="debrief")

PROVIDER = "claude"

#: Room enough for the reading and the thinking that produced it.
#:
#: A twelve-minute room is maybe fifteen exchanges, and the reply is a handful of
#: judgements of a sentence each — a few hundred tokens of answer. The budget is
#: for the thinking, which is the part being paid for.
MAX_OUTPUT_TOKENS = 8192

#: Tokens the model may spend reasoning before it answers.
#:
#: Must be below `MAX_OUTPUT_TOKENS`, which covers both. Set high relative to the
#: answer because the answer is short and the work is not: reading fifteen
#: exchanges and deciding which three answers were weakest is the entire value of
#: this call, and a thinking budget trimmed to save cents on an unmetered phase
#: buys back exactly the failure the phase exists to prevent.
THINKING_TOKENS = 4096

#: The name is part of the contract with the model and appears in the reply.
TOOL = "report_weak_answers"

_TOOL_SCHEMA: ToolParam = {
    "name": TOOL,
    "description": (
        "Report the answers that were weakest in this session, worst first — "
        "and separately, the answers that held."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "weak": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ordinal": {
                            "type": "integer",
                            "description": (
                                "The numbered line of the QUESTION this is about."
                            ),
                        },
                        "quote": {
                            "type": "string",
                            "description": (
                                "Words copied exactly from that line. Checked "
                                "against the transcript; a judgement whose quote "
                                "does not appear there is discarded."
                            ),
                        },
                        "weakness": {
                            "type": "string",
                            "enum": [weakness.value for weakness in Weakness],
                        },
                        "why": {
                            "type": "string",
                            "description": (
                                "One or two sentences addressed to the presenter, "
                                "saying what was missing. Specific to what they "
                                "actually said."
                            ),
                        },
                    },
                    "required": ["ordinal", "quote", "weakness", "why"],
                },
            },
            "held": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ordinal": {
                            "type": "integer",
                            "description": (
                                "The numbered line of the QUESTION this is about."
                            ),
                        },
                        "quote": {
                            "type": "string",
                            "description": (
                                "Words copied exactly from that line. Checked "
                                "against the transcript; an entry whose quote "
                                "does not appear there is discarded."
                            ),
                        },
                        "strength": {
                            "type": "string",
                            "enum": [strength.value for strength in Strength],
                            "description": (
                                "'held': a figure survived being pressed. "
                                "'grounded': a mechanism explained or a source "
                                "named, rather than asserted. 'conceded': a "
                                "limit admitted cleanly instead of bluffed "
                                "through. 'direct': the question asked was the "
                                "question answered."
                            ),
                        },
                        "why": {
                            "type": "string",
                            "description": (
                                "One or two sentences addressed to the "
                                "presenter, saying what worked in what they "
                                "actually said. Never generic praise."
                            ),
                        },
                    },
                    "required": ["ordinal", "quote", "strength", "why"],
                },
            },
        },
        # Both required, so an empty room reports two empty lists rather than
        # omitting one — an omitted `held` and a room where nothing held are
        # different facts.
        "required": ["weak", "held"],
    },
}


class ClaudeWeaknessReader:
    """Reads a finished room and says what went badly in it."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = model
        # `http_client` exists so the tests drive a real SDK client over a
        # transport that never leaves the process. Translation is where the bugs
        # live and it should not need an account to exercise.
        self._client = AsyncAnthropic(api_key=api_key, http_client=http_client)

    async def rank(self, *, room: Sequence[Annotated]) -> WeaknessReading:
        """One call, offline, after everything."""
        reply = await self._client.messages.create(
            model=self._model,
            max_tokens=MAX_OUTPUT_TOKENS,
            thinking={"type": "enabled", "budget_tokens": THINKING_TOKENS},
            tools=[_TOOL_SCHEMA],
            system=INSTRUCTION,
            messages=[MessageParam(role="user", content=render(room))],
        )

        reported = _reported(reply)
        return WeaknessReading(
            judged=to_judgements(reported),
            strong=to_strengths(reported),
            usage=TurnUsage(
                input_tokens=reply.usage.input_tokens,
                output_tokens=reply.usage.output_tokens,
            ),
        )


def _reported(reply: Any) -> Any:
    """The tool call's arguments, or nothing if the model did not make one.

    A reply with no tool block is the ordinary shape of *"I found nothing"* once
    thinking is enabled — the model reasons and then declines to call. Treating
    it as an error would turn a clean room into a failed debrief.
    """
    for block in reply.content:
        if getattr(block, "type", None) == "tool_use" and block.name == TOOL:
            return block.input
    return {}
