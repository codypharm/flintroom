"""Does a disputing panelist say something real, or argue on cue?

    cd backend && set -a && . ./.env && set +a && uv run python -m scripts.dispute

`app/agents/dispute.py` decides the *occasion* — different domains, not itself,
cap unspent — and the composer decides the *substance*. The gate is unit-tested
and cannot be wrong. What no test can answer is whether the line that comes back
is a genuine difference of priority or a room arguing because it was allowed to.

Two things are counted, because both are checkable:

    asked       the line still puts a question to the presenter
                (want 8/8 — a disagreement that forgets to interrogate has
                spent a metered turn on nothing)
    named       the line refers to the colleague at all
                (want high — otherwise the dispute is invisible to the listener
                and the whole feature is a prompt nobody can hear)

**The third thing matters most and only a person can score it: is the colleague's
question left standing?** A panelist that talks the room out of a valid challenge
sends somebody away having rehearsed the wrong thing, which is the failure this
design exists to prevent. The lines are printed in full for exactly that reason.

Costs one composition call per pair.
"""

from __future__ import annotations

import asyncio
import os

import httpx

from app.agents.archetypes import by_name
from app.agents.context import USER, Grounding, Said, TurnContext
from app.agents.dispute import contested
from app.agents.panel_models.gemini import GeminiPanelModel

PANEL = tuple(by_name(name) for name in ("cfo", "technical_skeptic", "champion"))

#: Each entry is a room paused just after one panelist asked something, with a
#: *different* panelist about to speak. The asker's question is always a fair
#: one — that is the point. A disagreement is only interesting when there was
#: nothing wrong with what it is disagreeing with.
SCENARIOS = [
    ("cfo", "Where does sixty-one percent gross margin come from?", "technical_skeptic"),
    ("cfo", "What did you spend to acquire each of those customers?", "champion"),
    ("technical_skeptic", "What happens to latency at ten times the load?", "cfo"),
    ("technical_skeptic", "What stops a competitor rebuilding this in a quarter?", "champion"),
    ("champion", "What is the one proof point I can take into the committee?", "cfo"),
    ("champion", "Who inside the company will sponsor this?", "technical_skeptic"),
    ("cfo", "How long does the cash last at this burn?", "technical_skeptic"),
    ("technical_skeptic", "Who owns the data once it leaves the device?", "cfo"),
]

SAID = "We rebuilt onboarding last quarter and it moved everything."


async def main() -> None:
    async with httpx.AsyncClient(timeout=90) as http:
        model = GeminiPanelModel(api_key=os.environ["GEMINI_API_KEY"], http=http)

        asked = named = 0

        for asker, question, speaker in SCENARIOS:
            archetype = by_name(speaker)
            context = TurnContext(
                said=SAID,
                grounding=Grounding(
                    transcript=(
                        Said(speaker=USER, text="We are growing quickly."),
                        Said(speaker=asker, text=question),
                    )
                ),
            )

            dispute = contested(archetype, PANEL, context, spent=0)
            if dispute is None:
                print(f"{speaker:18} GATE CLOSED against {asker}")
                continue

            reply = await model.compose(
                archetype=archetype, context=context, dispute=dispute
            )
            line = reply.text.strip()

            asked += "?" in line
            named += asker.split("_")[0] in line.lower()

            print(f"\n{asker} asked: {question}")
            print(f"{speaker} says: {line}")

        print(
            f"\nasked {asked}/{len(SCENARIOS)}   named {named}/{len(SCENARIOS)}"
            "\nRead the lines: is each colleague's question still standing?"
        )


if __name__ == "__main__":
    asyncio.run(main())
