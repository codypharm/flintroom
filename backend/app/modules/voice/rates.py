"""What a room's measured usage costs, in dollars.

`session_costs` has carried a column per vendor since Phase 2 and
`computed_cost_usd` beside them, and nothing has ever written that last one. So
the column Open Risk #4 exists to fill has been null on every row, and the
per-account daily spend ceiling `CLAUDE.md` requires had no figure to read.

**These are published rates, not observations.** `docs/voice-cost.md` is the
source and states the caveat in its own words: the measured *usage* is a
property of the product and the *rate* is a property of the contract, which
"swings several-fold across tiers". #14 is what replaces this with an invoice.

That is good enough for what this is for. A circuit breaker wants an estimate
that is right to within a factor of two; a pricing decision wants an invoice,
and `CLAUDE.md` already forbids the second without §4.3 behind it.

**Rates live here rather than in settings**, deliberately. A per-deployment
override would let two environments disagree about what a room cost, and the
figure is meant to be comparable across every row in the table. Changing one is
a code change with a diff, which is what a number this load-bearing should be.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

#: Scribe, $0.39/hr. `docs/voice-cost.md` calls this verified — read from the
#: vendor rather than assumed, and traced to `transcribers/elevenlabs.py`.
STT_USD_PER_SECOND = Decimal("0.39") / Decimal(3600)

#: Flash v2.5 at 0.5 credits/character, read off a quota error that stated its
#: own arithmetic. Converted through the ~$0.04 per interrogation minute that
#: `docs/voice-cost.md` derives from 371 characters/minute.
#:
#: **The single most important number here.** Synthesis is ~88% of a room, so
#: a cost model wrong on this line is wrong about the room; the other two are
#: rounding errors by comparison.
TTS_USD_PER_CHARACTER = Decimal("0.04") / Decimal(371)

#: `gemini-3.5-flash-lite`, from the $0.0003 per interrogation minute in
#: `docs/voice-cost.md` against 2,495 input and 80 output tokens. Split by the
#: usual 4:1 output-to-input ratio rather than measured separately, because at
#: 0.6% of the bill the split cannot move the total enough to matter.
LLM_USD_PER_INPUT_TOKEN = Decimal("0.0000001")
LLM_USD_PER_OUTPUT_TOKEN = Decimal("0.0000004")

#: Six places, which is smaller than any single room and larger than any error
#: that could accumulate over a day's worth of them. Two would round a whole
#: abandoned room to zero.
PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class Usage:
    """What a room consumed, named as `session_costs` names it.

    The field names are the column names on purpose: a caller holding a
    `SessionCost` row builds one of these without writing a mapping that can
    silently drift from the table it mirrors.

    **Synthesis is one number, and it understates.** `docs/voice-cost.md`
    records that the opener and the coach use the expressive model at exactly
    twice Flash per character, and `session_costs` has one character column, so
    those characters are priced at the cheaper rate. The bias is small for a
    real room — a dozen words against 371 characters per *minute* — and largest
    for an abandoned one, where the opener is the only synthesis there is.
    Splitting the column is #14's to do if the reconciliation needs it.
    """

    stt_seconds: int = 0
    tts_characters: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0


def cost_usd(usage: Usage) -> Decimal:
    """What that usage cost us, to the nearest millionth of a dollar.

    `Decimal` throughout and never a float. This lands in a `Numeric` column and
    is summed to compare against a ceiling, and a float would make the answer
    depend on the order the rows came back in.
    """
    return (
        usage.stt_seconds * STT_USD_PER_SECOND
        + usage.tts_characters * TTS_USD_PER_CHARACTER
        + usage.llm_input_tokens * LLM_USD_PER_INPUT_TOKEN
        + usage.llm_output_tokens * LLM_USD_PER_OUTPUT_TOKEN
    ).quantize(PLACES)
