"""Does a reasoning model actually read a room, or just agree that it was bad?

    cd backend && set -a && . ./.env && set +a && uv run python -m scripts.weakness

`docs/debrief-and-sparring.md` decision 2 moved the weak-answer verdict from
code into a model, on one argument above all others: **no rule expressible in
code can see a fluent, specific, confidently wrong answer**, and catching that is
what `Product.md` §1 means by attacking substance rather than delivery.

That argument is worth exactly nothing until a model has been shown to do it.

The room below is planted. Every line is ordinary and five of them are traps:

    [1]  answered fluently and WRONGLY. $1,200 at $180/month is 6.7 months of
         payback, not four. On topic, specific, confident, contradicting nothing
         else said — invisible to every structural rule, and to the Auditor,
         which compares a figure against its own earlier value rather than
         against arithmetic. THIS IS THE ONE THE DESIGN WAS CHANGED FOR.
    [3]  answered *well*, with a named customer, a number and a date. Must not
         appear. A reader that flags everything has told you nothing.
    [5]  never answered. The presenter talks past it.
    [9]  a colleague cut across it. Carries CUT_ACROSS. Must not be filed as the
         presenter dodging — that is the accusation #56 exists to prevent.
    [12] the room ran out on it. Carries ENDED_AT_THE_CAP. Same fairness bar.

What is counted is what is checkable. What matters most — whether the reasons
read like something a person would say — is printed in full, because only a
person can score that.

Costs one call.

MEASURED 2026-08-17, `gemini-3.7-flash`, 584 input / ~299 output tokens:

    caught the wrong answer [1]   YES  — "Your math does not hold up: at $180 a
                                         month, recovering a $1,200 acquisition
                                         cost takes nearly seven months rather
                                         than four."
    caught the unanswered  [5]   YES
    left the good answer   [3]   YES  — no false positive
    filed fairly           [9]   YES (dismissed)
    filed fairly          [12]   YES (not_reached)

**The first line is the whole argument for decision 2 landing.** Nothing
structural could reach it: the answer has a figure in it, sits on the question
asked, is never pressed, and contradicts nothing said elsewhere.

Two things the run corrected rather than confirmed:

- The first attempt filed [9] as `unanswered` while its own `why` said *"you
  were interrupted by another panelist before you had an opportunity to
  answer"* — a right reading with the wrong label, because the Gemini schema
  listed six bare enum strings and no meanings. Descriptions fixed it. The
  Claude tool schema had carried them all along, which is how the gap survived
  review.
- [1] came back `contradicted` rather than `unsupported`, against a definition
  that said "a figure conflicts with one they gave *earlier*". The model was
  right and the definition was narrow; `Weakness.CONTRADICTED` now covers two
  of the presenter's own figures disagreeing inside one answer.

**Ordering moves between runs.** Two runs, identical membership, [1] ranked
first and then second. Read a single run's order as a signal about the room and
not as a stable fact — the same caution `scripts/rotation.py` records about its
±2 band.
"""

from __future__ import annotations

import asyncio
import os

import httpx

from app.agents.context import USER, Said
from app.agents.weakness import weak_answers
from app.agents.weakness_models.gemini import GeminiWeaknessReader
from app.modules.sessions.schemas import EndReason

ROOM = (
    Said(speaker=USER, text="We are at two million ARR, growing forty percent quarter on quarter."),
    Said(speaker="cfo", text="What does it cost you to acquire a customer, and how long until that pays back?"),
    Said(speaker=USER, text="Acquisition cost is twelve hundred dollars, and a customer pays us a hundred and eighty a month, so payback lands around four months."),
    Said(speaker="champion", text="What is the single proof point I could take into my committee?"),
    Said(speaker=USER, text="Ramp rolled us out to four hundred seats in March and renewed early in June with a twenty percent expansion."),
    Said(speaker="technical_skeptic", text="What happens to your latency at ten times the current load?"),
    Said(speaker=USER, text="We are really excited about what is coming on the roadmap next quarter."),
    Said(speaker="cfo", text="Who owns the security review on your side?"),
    Said(speaker=USER, text="Our head of platform owns it."),
    Said(speaker="champion", text="How long does it take a new customer to see value?"),
    Said(
        speaker="cfo",
        text="Time to value matters less than the burn. What is your runway at this spend?",
        disputed=True,
    ),
    Said(speaker=USER, text="About fourteen months."),
    Said(speaker="technical_skeptic", text="What stops a competitor rebuilding this in a quarter?"),
)

#: Ordinal → what a correct reading does with it.
PLANTED = {
    1: "THE WRONG ANSWER (payback is 6.7 months, not 4)",
    3: "a good answer — must NOT appear",
    5: "never answered",
    9: "a colleague cut across it — not the presenter's fault",
    12: "the room ran out — not the presenter's fault",
}

#: Filing one of these as anything else is blaming somebody for a question they
#: were not given.
FAIR = {9: "dismissed", 12: "not_reached"}


async def main() -> None:
    async with httpx.AsyncClient(timeout=180) as http:
        reader = GeminiWeaknessReader(api_key=os.environ["GEMINI_API_KEY"], http=http)

        ranked = await weak_answers(
            ROOM, ended=EndReason.SESSION_CAP, reader=reader
        )

    answers = ranked.answers
    found = {answer.ordinal for answer in answers}

    for rank, answer in enumerate(answers, start=1):
        planted = PLANTED.get(answer.ordinal, "")
        print(f"\n{rank}. [{answer.ordinal}] {answer.weakness.value.upper()}  {planted}")
        print(f"   asked by {answer.asked_by}: {answer.question}")
        print(f"   they said: {answer.answer or '— nothing —'}")
        print(f"   why: {answer.why}")

    filed = {answer.ordinal: answer.weakness.value for answer in answers}

    print("\n" + "=" * 70)
    print(f"caught the wrong answer [1]   {'YES' if 1 in found else 'NO — the reason for the whole design'}")
    print(f"caught the unanswered  [5]   {'YES' if 5 in found else 'NO'}")
    print(f"left the good answer   [3]   {'YES' if 3 not in found else 'NO — false positive'}")

    for ordinal, expected in FAIR.items():
        got = filed.get(ordinal)
        if got is None:
            print(f"blamed nobody for     [{ordinal}]   MISSING — belongs on the list")
        elif got == expected:
            print(f"filed fairly          [{ordinal}]   YES ({got})")
        else:
            print(f"filed fairly          [{ordinal}]   NO — called it '{got}', not '{expected}'")

    print(
        f"\n{len(answers)} returned, {ranked.usage.input_tokens} in / "
        f"{ranked.usage.output_tokens} out. Read the reasons: would a person say them?"
    )


if __name__ == "__main__":
    asyncio.run(main())
