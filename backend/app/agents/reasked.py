"""Whether a panelist is about to ask something it has already asked.

Reported by a tester on 2026-09-26: the floor moved away from the CFO and back,
and the CFO returned with the question it had already put. The composer is told
not to — its prompt lists this archetype's earlier questions under *"do not
repeat these"* — and until this module nothing checked. A persona pulls toward
its subject harder than one sentence pulls away from it, and hardest in a room
with no deck and a thin opening, where there is least else to ask about.

**Lexical, on purpose.** Words in common over words in either, after dropping
the ones every question shares. It catches the reported symptom — the same
question, reworded around the edges — and it is deterministic, free, and
answerable in a test. A model asked "are these the same question?" would catch
looser paraphrase and would cost a hop on a live turn, and #43 measured what a
model's judgement is worth when it is asked for one.

**It must not catch a new question on the same subject.** Two margin questions
from the CFO are the CFO doing its job, and `context.py` already records which
failure is worse: a panelist steered off the ground it exists to press. The
threshold sits where rewording is caught and a second question is not, and the
tests pin both sides.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

#: Share of words in either line that must appear in both. At 0.6 a question
#: moved around by a leading "so" or a swapped verb form is still the question;
#: two margin questions asking different things sit near 0.3.
SAME_ENOUGH = 0.6

#: Below this many words that carry meaning, an overlap score is noise — two
#: words in common out of three is not evidence of anything. Short lines are
#: compared word for word instead.
FEWEST_WORDS = 4

#: The words every question is made of, and so say nothing about which question
#: it is. Deliberately short: a word that belongs to a subject — "margin",
#: "users", "cost" — must never be in here, or two different questions about it
#: would look identical.
_FILLER = frozenset(
    """
    a an the and or but so then now just really actually well okay ok right
    i me my we us our you your he she it its they them their this that these
    those there here what which who whom whose when where why how
    is are was were be been being am do does did done have has had having
    will would can could should shall may might must
    to of in on at by for from with about into over under up down out off
    if than as not no yes too very also again still even let lets tell walk
    """.split()
)


def _words(text: str) -> list[str]:
    """Every word, lower-cased, apostrophes kept so "what's" stays one word."""
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower())


def _meaning(words: list[str]) -> frozenset[str]:
    """The words that say what this question is about, crudely stemmed.

    The stemming is one rule — a trailing plural `s` — because that is the
    difference rewording actually produces ("gets you" against "you get"), and
    every rule past it is a way for two different words to collide.
    """
    kept = set()
    for word in words:
        word = word.split("'")[0]
        if word in _FILLER:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        kept.add(word)
    return frozenset(kept)


def already_asked(line: str, earlier: Sequence[str]) -> str | None:
    """The earlier question this line repeats, or `None` if it asks something new.

    Returns the question rather than a flag, because the caller's next step is
    to tell the composer which one it was about to repeat — a rewrite told only
    "not that" writes the nearest neighbour.
    """
    said = _words(line)
    mine = _meaning(said)
    for question in earlier:
        theirs_said = _words(question)
        if said == theirs_said:
            return question
        theirs = _meaning(theirs_said)
        if min(len(mine), len(theirs)) < FEWEST_WORDS:
            continue
        if len(mine & theirs) / len(mine | theirs) >= SAME_ENOUGH:
            return question
    return None
