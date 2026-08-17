"""Can a panelist press their own question, and only when it was dodged?

    cd backend && set -a && . ./.env && set +a && uv run python -m scripts.followup

The companion to `scripts/rotation.py`, and neither is meaningful alone.
Rotation asks whether the floor moves around; this asks whether it can stay put
when staying put is the right answer. A change to `_SELECTION_INSTRUCTION` that
improves one at the other's expense is the trade recorded in
`docs/panel-orchestration.md`, and both numbers have to be seen to know it
happened.

Each scenario is a room several turns in where somebody has just asked something
and the presenter has either answered it or dodged it. Two numbers:

    pressed-dodge    the asker takes the floor again after an evasion
                     (want high — this is the interrogation)
    pressed-answer   the asker takes the floor again after a real answer
                     (want low — this is the monopoly)

**High on both is the failure mode, not a pass.** Measured, an instruction asking
the model whether the presenter dodged scored 4/4 and 4/4: asked for a judgement
it returns the agreeable one, and a rule that always fires is not a rule. What
discriminates is asking for something checkable — whether the reply contains a
figure, a name, a date or a mechanism — which is the same extract-then-decide
split `docs/auditor-grounding.md` is built on.

Costs one selection call per scenario. Nothing here is deterministic; treat a
single scenario flipping as noise and the ratio across eight as the signal.
"""

from __future__ import annotations

import asyncio
import os
from collections import Counter
from dataclasses import dataclass

import httpx

from app.agents.archetypes import by_name
from app.agents.context import USER, Grounding, Said, TurnContext
from app.agents.panel_models.gemini import GeminiPanelModel

PANEL = tuple(by_name(name) for name in ("cfo", "technical_skeptic", "champion"))


@dataclass(frozen=True)
class Scenario:
    """One room, paused on the turn after a question."""

    asker: str
    question: str
    reply: str
    dodged: bool


#: Paired: every question appears twice, once dodged and once answered, so the
#: two rates are measured against identical ground and a rule cannot score well
#: by finding some questions more pressing than others.
#:
#: The dodges are the real article — reassurance, restatement, a change of
#: subject — rather than refusals, because a presenter who says "I won't tell
#: you" is not what rehearsal is for. The answers are specific but not
#: necessarily *good*: "eleven hundred blended" invites a harder question, and it
#: still has to count as an answer, or the rule presses forever.
SCENARIOS = (
    Scenario(
        asker="cfo",
        question="Where does sixty-one percent gross margin come from?",
        reply="Margin has always been a real strength for us and the team stays very focused on it.",
        dodged=True,
    ),
    Scenario(
        asker="cfo",
        question="Where does sixty-one percent gross margin come from?",
        reply="Hosting is nine points, support is six, payment fees are four. That leaves sixty-one.",
        dodged=False,
    ),
    Scenario(
        asker="technical_skeptic",
        question="What happens to latency at ten times the load?",
        reply="We are really confident in the architecture, it was built to scale from day one.",
        dodged=True,
    ),
    Scenario(
        asker="technical_skeptic",
        question="What happens to latency at ten times the load?",
        reply="We load tested to twelve times last month. The ninety-ninth percentile went from forty to ninety-five milliseconds.",
        dodged=False,
    ),
    Scenario(
        asker="champion",
        question="What is the one proof point I can take into the committee?",
        reply="Honestly there are so many, the whole story together is what makes it compelling.",
        dodged=True,
    ),
    Scenario(
        asker="champion",
        question="What is the one proof point I can take into the committee?",
        reply="Northwind cut their close time by a third and their finance director will take a reference call.",
        dodged=False,
    ),
    Scenario(
        asker="cfo",
        question="What did you spend to acquire each of those customers?",
        reply="Acquisition is something we have got a lot smarter about over the past year.",
        dodged=True,
    ),
    Scenario(
        asker="cfo",
        question="What did you spend to acquire each of those customers?",
        reply="Eleven hundred dollars blended. It was fourteen hundred a year ago.",
        dodged=False,
    ),
)


def context_for(scenario: Scenario) -> TurnContext:
    """A room with all three seated and `scenario.asker` holding the question.

    All three have spoken, deliberately. Rule 1 hands the floor to anybody marked
    "has not spoken yet" and would decide every scenario before rule 2 was
    reached, so a warm room is the only place the follow-up rule is observable.
    """
    others = [archetype.name for archetype in PANEL if archetype.name != scenario.asker]
    return TurnContext(
        said=scenario.reply,
        grounding=Grounding(
            transcript=(
                Said(speaker=USER, text="We are growing quickly and the fundamentals are strong."),
                Said(speaker=others[0], text="Growing from what base, though?"),
                Said(speaker=USER, text="From a small one, but the trajectory is what matters."),
                Said(speaker=others[1], text="What changed to make the trajectory bend?"),
                Said(speaker=USER, text="We rebuilt onboarding and it moved everything."),
                Said(speaker=scenario.asker, text=scenario.question),
            )
        ),
    )


async def main() -> None:
    async with httpx.AsyncClient(timeout=90) as http:
        model = GeminiPanelModel(api_key=os.environ["GEMINI_API_KEY"], http=http)

        pressed: Counter[str] = Counter()
        total: Counter[str] = Counter()
        picks = []

        for scenario in SCENARIOS:
            reply = await model.select(candidates=PANEL, context=context_for(scenario))
            kind = "dodge" if scenario.dodged else "answer"
            total[kind] += 1
            if reply.text == scenario.asker:
                pressed[kind] += 1
            picks.append(
                f"{'D' if scenario.dodged else 'A'}:"
                f"{'PRESS' if reply.text == scenario.asker else reply.text[:2]}"
            )

        print(
            f"pressed-dodge {pressed['dodge']}/{total['dodge']}   "
            f"pressed-answer {pressed['answer']}/{total['answer']}\n"
            f"{' '.join(picks)}"
        )


if __name__ == "__main__":
    asyncio.run(main())
