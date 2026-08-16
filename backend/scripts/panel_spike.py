"""Put a real panel turn against a clock.

    uv run python -m scripts.panel_spike                  # 3 turns
    uv run python -m scripts.panel_spike --turns 1        # cheapest useful run
    uv run python -m scripts.panel_spike --no-grounding   # deckless room

The measurement `docs/panel-orchestration.md` says every remaining Phase 3
decision is downstream of. Open Risk #3 puts the illusion's threshold at ~1.5s,
and every latency claim about the orchestrated loop so far is an assumption.

**This measures two of the chain's hops, not all of it.** A live turn is:

    speech ends → endpointing → transcription → SELECT → COMPOSE → speech → played

and what runs here is routing plus `COMPOSE`. Routing is code now — that is what
this spike's first run bought, by showing a model round trip cost ~0.8s of the
budget for what is mostly a lookup. Transcription and synthesis are still unbuilt
and unchosen, so the number this prints remains a *floor*: whatever it says, the
real chain is that plus two vendors that have not been picked.

It drives the **shipping** adapter — `GeminiPanelModel`, the real prompts, the
real archetypes — rather than a second implementation written to agree with it. A
spike that assembles its own prompt measures the spike.

No tests. It is an instrument, not a feature: what it reports is one afternoon's
behaviour from a provider, which is not a thing a test suite can hold still. The
code it exercises is tested; this reports on reality.
"""

from __future__ import annotations

import argparse
import asyncio
import time

import httpx

from app.agents.archetypes import DEFAULT_PANEL, LIBRARY
from app.agents.context import USER
from app.agents.panel import Grounding, Said, interrogate
from app.agents.panel_models import build_panel_model
from app.core.config import Settings, get_settings

#: What a presenter says, turn by turn.
#:
#: Written to range deliberately across subjects rather than to be realistic
#: prose. Three turns about money cannot tell a routing problem from a room
#: correctly following the topic — which is what the first version of this
#: script could not answer, and why every turn went to the CFO.
#:
#: Turn 3 contradicts the deck below, which is the case targeted interruption
#: exists for. The rest each sit clearly in a different archetype's ground, so
#: a room that still gives every turn to one voice is failing rather than
#: agreeing.
SCRIPT = (
    "We're at four hundred thousand in ARR, growing about twenty percent a month.",
    "Acquisition is mostly outbound right now, and it's working.",
    "Our gross margin is around seventy percent and improving.",
    "We built it all on our own infrastructure. It handles a thousand concurrent "
    "sessions today.",
    "Users tell us the onboarding is confusing, but almost nobody churns once "
    "they're through it.",
    "Enterprise buyers keep asking for SOC 2. We're starting the audit next "
    "month.",
    "Our biggest competitor raised a hundred million last quarter, but they're "
    "building the wrong thing.",
    "We have three reference customers who would take a call tomorrow.",
    "The one blocker is the platform team — we need them to expose an API before "
    "we can ship.",
    "Honestly the hardest part has been hiring senior engineers fast enough.",
)

#: A deck, as `Grounding` receives it — pre-rendered citable lines.
CLAIMS = (
    "Gross margin of 61% in Q3 2026 (slide 4)",
    "ARR of $400K as of Q3 2026 (slide 2)",
    "CAC payback of 14 months (slide 7)",
)

#: Above this the room stops feeling real (Open Risk #3).
THRESHOLD_SECONDS = 1.5


async def run(turns: int, grounded: bool, full: bool = False) -> None:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=30.0) as http:
        model = build_panel_model(settings, http)
        if model is None:
            raise SystemExit(
                "No panel model configured. Set GEMINI_API_KEY in backend/.env"
            )

        panel = LIBRARY if full else DEFAULT_PANEL
        _report_configuration(settings, grounded, panel)

        transcript: list[Said] = []
        composes: list[float] = []
        spoke: list[str] = []
        decided: list[str] = []

        for index in range(min(turns, len(SCRIPT))):
            said = SCRIPT[index]
            grounding = Grounding(
                claims=CLAIMS if grounded else (), transcript=tuple(transcript)
            )

            print(f"\n─── turn {index + 1}\nthem: {said}")

            started = time.perf_counter()
            turn = await interrogate(
                panel, said=said, grounding=grounding, model=model
            )
            elapsed = time.perf_counter() - started

            # One figure now, because there is one model call. Routing happens
            # in `agents/routing.py` and costs nothing measurable.
            print(f"{turn.archetype.title}: {turn.line}")
            print(f"      {elapsed:.2f}s{'  ⚠ over threshold' if elapsed > THRESHOLD_SECONDS else ''}")

            composes.append(elapsed)
            spoke.append(turn.archetype.name)
            decided.append(turn.chosen_by)
            # Both sides, because the router's whole job is reading how the last
            # answer went. A list of the panel's questions is half a room.
            transcript.append(Said(speaker=USER, text=said))
            transcript.append(Said(speaker=turn.archetype.name, text=turn.line))

        _report_timings(composes)
        _report_distribution(spoke, decided)


def _report_configuration(settings, grounded, panel) -> None:
    print(
        f"provider={settings.panel_provider} "
        f"compose={settings.panel_composition_model} "
        f"panel={len(panel)} grounded={grounded}"
    )


def _report_distribution(spoke: list[str], decided: list[str]) -> None:
    """Who actually got the floor, and what put them there.

    The number this exists for. A room where one archetype takes every turn is
    the failure §3.1's mixed panel is meant to prevent, and it is invisible from
    any single turn — each one reads perfectly reasonable on its own.
    """
    if not spoke:
        return

    print("\nwho spoke:")
    for name in dict.fromkeys(spoke):
        share = spoke.count(name) / len(spoke)
        print(f"  {name:22} {spoke.count(name):>2}  {'█' * round(share * 20)}")

    print("\nwhat chose them:")
    for how in dict.fromkeys(decided):
        print(f"  {how:22} {decided.count(how):>2}")


def _report_timings(totals: list[float]) -> None:
    if not totals:
        return

    worst = max(totals)
    mean = sum(totals) / len(totals)
    print(
        f"\n{len(totals)} turns — mean {mean:.2f}s, worst {worst:.2f}s, "
        f"threshold {THRESHOLD_SECONDS}s"
    )
    print(
        "This is one model call. Transcription and speech are unbuilt, so the "
        "live chain is this plus two hops that have not been chosen."
    )
    if worst > THRESHOLD_SECONDS:
        print(
            "⚠ Over threshold before the two missing hops exist. "
            "See docs/panel-orchestration.md."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=len(SCRIPT))
    parser.add_argument(
        "--full-library",
        action="store_true",
        help="run all eight archetypes rather than the three-person default room",
    )
    parser.add_argument(
        "--no-grounding",
        action="store_true",
        help="run the deckless room, which is a first-class path",
    )
    args = parser.parse_args()

    asyncio.run(run(args.turns, grounded=not args.no_grounding, full=args.full_library))


if __name__ == "__main__":
    main()
