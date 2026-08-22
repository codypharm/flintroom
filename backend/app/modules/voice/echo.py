"""#78 — recognising the panel's own voice coming back up the microphone.

On a device whose acoustic echo cancellation is weak or absent, the loudspeaker
reaches the microphone. Measured against the live transcriber
(`docs/echo-cancellation.md`), the failure is exactly one case: a panel line
returning **alone into a gap**, where it is the only voice and therefore the
primary speaker. Mixed under a talking presenter it is already rejected,
unaided. So the question this module answers is narrow — is this final the
room's last panel line, near verbatim, and nothing else?

Two thresholds, and the shape of each comes from a ruling rather than tuning:

- **Coverage**: the final must contain essentially the whole panel line.
  A completed playback echoes whole; a fragment can only be echo when playback
  was cut, and playback is only cut when the presenter is already talking —
  which is exactly the mix the transcriber is measured to reject. So a
  fragment ("Ten times?") is a person, and is kept.
- **Novelty**: the final may add at most one token beyond the panel line.
  A presenter who repeats the question *and keeps going* is thinking aloud,
  and the added words are what prove it — they must always pass. The one-token
  slack is for transcriber jitter, not for speech.

Both are computed on normalised tokens, because the observed echo differed from
its source only by "ten" → "10": the transcriber respells what it hears, and a
matcher that treats respelling as difference would miss the very pair the
ticket records.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

#: How much of the panel line the final must contain to be its echo. Below
#: this, too little of the line came back for a completed playback to explain
#: it — see the module docstring for why a partial return means a person.
COVERAGE_FLOOR = 0.8

#: How many tokens the final may add and still be nothing but the panel line.
#: One, for transcriber jitter — never more, because added words are how a
#: deliberate repeat proves there is a person behind it.
NOVELTY_CEILING = 1

#: The respellings a transcriber actually performs on played-back speech.
#: Number words only: the measured echo differed from its source by exactly
#: "ten" → "10", and digits are the one substitution a transcriber makes
#: routinely in both directions. Not a general normaliser — every entry here
#: widens what counts as "the same words", so it stays as small as the
#: evidence.
_RESPELLINGS = {
    word: str(figure)
    for figure, word in enumerate(
        (
            "zero", "one", "two", "three", "four", "five", "six", "seven",
            "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
            "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
        )
    )
} | {
    "thirty": "30", "forty": "40", "fifty": "50", "sixty": "60",
    "seventy": "70", "eighty": "80", "ninety": "90", "hundred": "100",
    "thousand": "1000",
}


def _tokens(text: str) -> tuple[str, ...]:
    """The words alone — case, punctuation and respelling folded away."""
    words = re.findall(r"[a-z0-9]+", text.casefold())
    return tuple(_RESPELLINGS.get(word, word) for word in words)


@dataclass(frozen=True, slots=True)
class EchoReading:
    """What comparing one final against one panel line found.

    The figures rather than a bare bool, because the refusal is logged and the
    log line may not carry the text (`CLAUDE.md`: no transcript in logs) — so
    these numbers are the only trace of *why* a line was refused that an
    operator will ever see.
    """

    #: Tokens of the final matched against the panel line.
    matched: int
    #: Tokens of the final the panel line does not account for.
    novel: int
    #: How much of the panel line the final contains, 0..1.
    coverage: float

    @property
    def is_echo(self) -> bool:
        return self.coverage >= COVERAGE_FLOOR and self.novel <= NOVELTY_CEILING


def hears_itself(panel: str, heard: str) -> EchoReading:
    """Is `heard` the room's own `panel` line returning, and the evidence.

    Matching blocks rather than a similarity ratio, deliberately: a ratio
    scores a verbatim repeat with a short continuation at ~0.86, indistinguishable
    from jittered echo — but the two separate perfectly on *what the final
    adds*, which blocks measure and a ratio blurs.
    """
    said = _tokens(panel)
    returned = _tokens(heard)
    if not said or not returned:
        return EchoReading(matched=0, novel=len(returned), coverage=0.0)
    matched = sum(
        block.size for block in SequenceMatcher(a=said, b=returned).get_matching_blocks()
    )
    return EchoReading(
        matched=matched,
        novel=len(returned) - matched,
        coverage=matched / len(said),
    )
