"""Does the room give the floor around, or does one archetype hold it?

The measurement behind *Giving the floor away* in `docs/panel-orchestration.md`.
Run it after any edit to `_SELECTION_INSTRUCTION` or `_silence_of` — the tests
pin that the two halves agree on their vocabulary, which is the failure that is
otherwise silent, but only a live model can say whether the room still rotates.

Imports the shipped prompt rather than a copy of it. A paraphrase that behaved
differently from the text actually sent is precisely the thing this has to be
unable to hide.

    cd backend && set -a && . ./.env && set +a && uv run python -m scripts.rotation

Costs one selection call per utterance per prefix length — 32 calls against
`gemini-3.5-flash-lite`, which is fractions of a cent, but it is not free and it
is not offline.

**One run is not evidence.** Measured 2026-08-17 across three runs of an
unchanged prompt, the busiest archetype moved by two out of eight in a single
column — wide enough to swallow any effect worth arguing about. Take the median
of at least three runs on each side, and treat a difference of one as nothing.
Several earlier before/after readings in `docs/panel-orchestration.md` were
single runs and are weaker than they read.

**Prefix length is a variable because a live room routes on an unfinished
sentence.** `OrchestratedChannel` starts selection on the first partial so the
hop overlaps the tail of the utterance, so a prompt that only behaves on a whole
sentence is a prompt that does not behave. The 3-word column is the one that
matters most and it is the one the old instruction failed hardest.
"""

from __future__ import annotations

import asyncio
import os
from collections import Counter

import httpx

from app.agents.archetypes import by_name
from app.agents.context import USER, Grounding, Said, TurnContext
from app.agents.panel_models.gemini import GeminiPanelModel

#: Three, not the full library. A bigger panel makes concentration look better by
#: arithmetic alone, and three is the composition `CLAUDE.md` requires by
#: default — a champion, a skeptic and a neutral.
PANEL = tuple(by_name(name) for name in ("cfo", "technical_skeptic", "champion"))

#: Deliberately mixed ground, and deliberately not balanced. Roughly half of
#: these are squarely the CFO's, which is what an honest corpus for this looks
#: like: a presenter talks about money more than about anything else. A fair
#: outcome is therefore not an even split — it is the CFO leading while the other
#: two are heard from, which is what the "after" numbers show.
SAID = [
    "Our gross margin held at sixty-one percent last quarter and we expect it to hold as we scale.",
    "Freight is already inside that number and has been for three quarters running.",
    "Our two largest customers renewed in April at higher prices than last year.",
    "We have eleven engineers and we plan to double that headcount by December.",
    "The replatform finishes in Q2 and after that our unit costs fall sharply.",
    "Nobody has churned since we changed the onboarding flow in February.",
    "We are the only team shipping this on device rather than in a datacentre.",
    "Support tickets dropped forty percent after the rewrite landed.",
]

#: What the chosen archetype is recorded as having asked, one per turn. Fixed
#: rather than composed, because composing them would double the cost and the run
#: time of an instrument that is about *who* speaks.
#:
#: **Each question is one the next utterance answers**, and that is load-bearing
#: rather than tidy. A single generic line repeated — which is what this was
#: first — makes every utterance a change of subject, so the transcript models a
#: presenter who evades all eight questions. `_SELECTION_INSTRUCTION` rule 2
#: presses on exactly that, correctly, and the run then reports concentration
#: that is the rule working rather than the bias returning. Measured: the same
#: prompt scored cfo ×4-5 with a repeated line and cfo ×2-3 with these.
#:
#: So this file measures one thing — does the floor move around when the
#: presenter is co-operating — and `scripts/followup.py` measures the other.
QUESTIONS = [
    "Is freight inside that number?",
    "Which customers renewed, and at what price?",
    "How big is the engineering team today?",
    "When does the replatform actually finish?",
    "And what has churn done since then?",
    "What stops a competitor rebuilding this?",
    "What did the rewrite actually buy you?",
    "So what breaks first when this scales?",
]


async def run(model: GeminiPanelModel, *, words: int | None) -> list[str]:
    """One room, routing on a prefix of `words` — or on the whole sentence."""
    transcript: list[Said] = []
    chosen: list[str] = []

    for turn, said in enumerate(SAID):
        shown = said if words is None else " ".join(said.split()[:words])
        reply = await model.select(
            candidates=PANEL,
            context=TurnContext(
                said=shown,
                grounding=Grounding(transcript=tuple(transcript)),
                # A truncated row *is* a partial — that is what it is simulating
                # — and until this was set the harness measured the production
                # path without the one flag the production path sets. Every
                # before/after taken with it missing compared two identical
                # prompts and read the noise as an effect.
                unfinished=words is not None,
            ),
        )
        chosen.append(reply.text)
        # The room carries on whoever was picked, so every column sees the same
        # kind of history rather than diverging into differently-shaped rooms.
        transcript.append(Said(speaker=USER, text=said))
        transcript.append(Said(speaker=reply.text, text=QUESTIONS[turn]))

    return chosen


async def main() -> None:
    async with httpx.AsyncClient(timeout=90) as http:
        model = GeminiPanelModel(api_key=os.environ["GEMINI_API_KEY"], http=http)

        for words in (3, 6, 12, None):
            picked = await run(model, words=words)
            spread = Counter(picked)
            # Consecutive repeats, separately from the spread. An even split can
            # still contain a panelist speaking three times running, and that is
            # the half of the fix the roster annotation is responsible for.
            repeats = sum(1 for one, next_ in zip(picked, picked[1:]) if one == next_)
            print(
                f"{'full' if words is None else f'{words}w':>5}  "
                f"{' '.join(name[:2] for name in picked)}   "
                f"distinct={len(spread)}  repeats={repeats}  {dict(spread)}"
            )


if __name__ == "__main__":
    asyncio.run(main())
