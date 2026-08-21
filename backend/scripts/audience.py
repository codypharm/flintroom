"""Does the audience note steer the room, and does it stay unspoken?

The measurement behind `docs/audience-context.md` §1 and §1a. Two questions a
test cannot answer, because both are about what a live model actually does with
a prompt rather than about what the prompt says:

1. **Does it stay unspoken?** #66 ships "shaped, never spoken" — the panel is
   steered by the note and never repeats it. `test_audience.py` proves the
   instruction is *in* the request. Only a live model can say whether it is
   obeyed, and #63 is the standing proof that our own hand-tuned prose can lose
   to a persona.

2. **Does it drag a panelist off its own domain?** Raised by the architect on
   2026-08-21 and never checked: seat only the Technical Skeptic, hand it a note
   about headcount, and it might start asking about hiring — which is the CFO's
   ground and not a question the Skeptic exists to ask. The concern is real
   because the note sits in the *user* turn while the persona sits in the system
   instruction, and a late, specific instruction can beat an early, general one.

    cd backend && set -a && . ./.env && set +a && uv run python -m scripts.audience

Costs one composition call per archetype per condition per utterance — 24
against `gemini-3.5-flash-lite`, fractions of a cent, but not free and not
offline.

**Scored by code, never by a model.** Asked *"did the panelist stay on topic?"* a
model returns the agreeable answer — #43 measured exactly that, 4 of 4 on dodges
and 4 of 4 on genuine answers. So both checks are keyword containment, which is
crude and cannot be talked into anything. The lines are printed in full because
the counts are the summary and the text is the evidence.

**One run is not evidence.** `scripts/rotation.py` learned this the hard way:
across three runs of an unchanged prompt the busiest archetype moved by two out
of eight. Take the median of at least three runs before believing a difference.
"""

from __future__ import annotations

import asyncio
import os

import httpx

from app.agents.archetypes import by_name
from app.agents.context import Grounding, TurnContext
from app.agents.panel_models.gemini import GeminiPanelModel

#: `Product.md` §3.1's own example, verbatim — the sentence the whole feature
#: was specified around, and the one the setup screen now prints as its example.
NOTE = "my VP hates anything that adds headcount"

#: The two ends of the question. The CFO owns cost and may legitimately follow
#: the note anywhere it leads; the Technical Skeptic does not, and is the one
#: that would be dragged off its ground if anything is.
SEATS = ("technical_skeptic", "cfo")

#: Ordinary presenter speech with nothing about hiring in it. If headcount
#: appears in a reply it came from the note, not from the utterance — which is
#: the whole point of choosing these.
SAID = [
    "The replatform finishes in Q2 and after that our unit costs fall sharply.",
    "Our gross margin held at sixty-one percent last quarter.",
    "Nobody has churned since we changed the onboarding flow in February.",
    "We serve about four thousand requests a second at peak today.",
    "The migration is the last big piece of work in front of us.",
    "Our two largest customers renewed in April at higher prices.",
]

#: Words that mean the reply went to hiring. Deliberately generous — a false
#: alarm here costs a second look, and a miss costs the finding.
HIRING = (
    "headcount", "hire", "hiring", "hires", "engineer", "staff", "recruit",
    "salar", "team size", "people",
)

#: Words that would mean the note was read back. "VP" is the tell: it is in the
#: note, it is in none of the utterances, and no archetype has any other reason
#: to say it.
SPOKEN = ("vp", "hates", "told us", "you mentioned", "you said your", "you wrote")


def _hit(line: str, words: tuple[str, ...]) -> list[str]:
    lowered = line.lower()
    return [word for word in words if word in lowered]


async def main() -> None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set — see the module docstring.")

    async with httpx.AsyncClient() as http:
        model = GeminiPanelModel(api_key=key, http=http)

        for name in SEATS:
            archetype = by_name(name)
            assert archetype is not None, name
            print(f"\n{'=' * 72}\n{archetype.title}  ({', '.join(archetype.domains)})\n{'=' * 72}")

            for described in (False, True):
                drifted = 0
                said_aloud = 0
                print(f"\n--- {'WITH the note' if described else 'no note'} ---")

                for said in SAID:
                    reply = await model.compose(
                        archetype=archetype,
                        context=TurnContext(
                            said=said,
                            grounding=Grounding(),
                            audience=NOTE if described else "",
                        ),
                    )
                    hiring = _hit(reply.text, HIRING)
                    spoken = _hit(reply.text, SPOKEN)
                    drifted += bool(hiring)
                    said_aloud += bool(spoken)

                    flags = "".join(
                        (" [HIRING]" if hiring else "", " [SPOKE IT]" if spoken else "")
                    )
                    print(f"  {reply.text}{flags}")

                print(f"  => hiring in {drifted}/{len(SAID)}, read back in {said_aloud}/{len(SAID)}")


if __name__ == "__main__":
    asyncio.run(main())
