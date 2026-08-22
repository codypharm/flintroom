"""OpenAI against Gemini as the panel model, on the same prompts. #13.

Four measurements per vendor, in the order the task names them:

1. Warm selection and composition latency, against the fixed roster and
   transcript `scripts/rotation.py` uses — comparable to the incumbent's
   measured table in `docs/panel-orchestration.md`.
2. Rotation: does the floor move around, or does one archetype hold it (#43)?
   Reuses `scripts.rotation.run` verbatim so both vendors face the identical
   procedure. Three runs a column; one run is not evidence.
3. Figure invention (#45), roughly: numbers in the composed line that appear
   nowhere in what the model was shown. A composer may repeat the presenter's
   sixty-one percent; a composer that says "your CAC of $400" invented it.
4. Cost per turn from each vendor's own usage report, priced at LIST rates —
   marked as such, because §4.3 has not reconciled a single invoice yet (#14).

    cd backend && set -a && . ./.env && set +a && uv run python -m scripts.panel_compare

Costs a few hundred small-model calls. Cents, not free, not offline.
"""

from __future__ import annotations

import asyncio
import os
import re
import statistics
import time
from collections import Counter

import httpx

from app.agents.context import Grounding, Said, TurnContext, USER
from app.agents.panel_models.gemini import GeminiPanelModel
from app.agents.panel_models.openai import OpenAIPanelModel
from scripts.rotation import PANEL as _SEATED, QUESTIONS, SAID, run

#: `by_name` answers `Archetype | None` and rotation.py never narrows it; this
#: file is type-checked, so it does.
PANEL = tuple(one for one in _SEATED if one is not None)

#: USD per million tokens, LIST rates as of 2026-08 — unverified against any
#: invoice, which is exactly the #14 caveat. Update from the vendors' pricing
#: pages before believing a margin with these in it.
LIST_PRICES = {
    "gemini-3.5-flash-lite": (0.10, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
}

LATENCY_SAMPLES = 8
COMPOSE_SAMPLES = 6


def context_at(turn: int) -> TurnContext:
    transcript: list[Said] = []
    for earlier in range(turn):
        transcript.append(Said(speaker=USER, text=SAID[earlier]))
        transcript.append(Said(speaker=PANEL[earlier % 3].name, text=QUESTIONS[earlier]))
    return TurnContext(said=SAID[turn], grounding=Grounding(transcript=tuple(transcript)))


async def latencies(model) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {"select": [], "compose": []}
    # One unmeasured call to warm the connection, like the incumbent's table.
    await model.select(candidates=PANEL, context=context_at(3))

    for sample in range(LATENCY_SAMPLES):
        began = time.monotonic()
        await model.select(candidates=PANEL, context=context_at(3 + sample % 4))
        out["select"].append(time.monotonic() - began)

    for sample in range(LATENCY_SAMPLES):
        began = time.monotonic()
        await model.compose(archetype=PANEL[sample % 3], context=context_at(3 + sample % 4))
        out["compose"].append(time.monotonic() - began)

    return out


def shown_digits(context: TurnContext, archetype) -> set[str]:
    corpus = context.said + " ".join(said.text for said in context.grounding.transcript)
    corpus += archetype.attack_strategy
    return set(re.findall(r"\d+", corpus))


async def inventions(model) -> tuple[int, int, list[str]]:
    """Composed lines carrying a number the model was never shown."""
    invented = 0
    lines: list[str] = []
    for sample in range(COMPOSE_SAMPLES):
        archetype = PANEL[sample % 3]
        context = context_at(2 + sample % 5)
        reply = await model.compose(archetype=archetype, context=context)
        lines.append(f"[{archetype.name}] {reply.text}")
        fresh = set(re.findall(r"\d+", reply.text)) - shown_digits(context, archetype)
        if fresh:
            invented += 1
    return invented, COMPOSE_SAMPLES, lines


async def cost_per_turn(model, price_key: str) -> tuple[float, float]:
    """(select, compose) in USD, from the vendor's own usage report."""
    input_price, output_price = LIST_PRICES[price_key]
    select = await model.select(candidates=PANEL, context=context_at(4))
    compose = await model.compose(archetype=PANEL[0], context=context_at(4))

    def priced(usage) -> float:
        return (usage.input_tokens * input_price + usage.output_tokens * output_price) / 1e6

    return priced(select.usage), priced(compose.usage)


async def rotation(model) -> None:
    for words in (3, 6, 12, None):
        for attempt in range(3):
            picked = await run(model, words=words)
            spread = Counter(picked)
            repeats = sum(1 for one, next_ in zip(picked, picked[1:]) if one == next_)
            print(
                f"    {'full' if words is None else f'{words}w':>5} run{attempt + 1}  "
                f"{' '.join(name[:2] for name in picked)}   "
                f"distinct={len(spread)}  repeats={repeats}  {dict(spread)}"
            )


async def measure(name: str, model, price_key: str) -> None:
    print(f"\n=== {name} ({price_key}) ===")

    laid = await latencies(model)
    for call, times in laid.items():
        print(
            f"  {call}: median {statistics.median(times):.2f}s  "
            f"p90 {sorted(times)[int(len(times) * 0.9) - 1]:.2f}s  "
            f"({', '.join(f'{t:.2f}' for t in times)})"
        )

    select_usd, compose_usd = await cost_per_turn(model, price_key)
    print(f"  cost/turn (list): select ${select_usd:.6f}  compose ${compose_usd:.6f}")

    invented, of, lines = await inventions(model)
    print(f"  invented figures: {invented}/{of} lines carried an unshown number")
    for line in lines:
        print(f"    {line}")

    print("  rotation:")
    await rotation(model)


async def main() -> None:
    async with httpx.AsyncClient(timeout=90) as http:
        await measure(
            "Gemini (incumbent)",
            GeminiPanelModel(api_key=os.environ["GEMINI_API_KEY"], http=http),
            "gemini-3.5-flash-lite",
        )
        await measure(
            "OpenAI",
            OpenAIPanelModel(api_key=os.environ["OPENAI_API_KEY"], http=http),
            "gpt-5-mini",
        )


if __name__ == "__main__":
    asyncio.run(main())
