"""Who speaks next, decided in code.

Measured, a model round trip for this costs ~0.8s of a 1.5s budget
(`docs/panel-orchestration.md`) — for a decision that is mostly a lookup. So the
whole budget goes to the hop that writes the line, and this one spends nothing.

**It is deliberately dumb, and the trade is worth stating.** What it gives up is
comprehension: a model would understand an answer that is entirely about margin
without ever using the word. What it buys is the turn happening at all, which is
the constraint that was actually failing.

The signals are the ones already in the data. Nothing here infers anything.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.agents.archetypes import Archetype
from app.agents.context import USER
from app.agents.repeat import MOST_WORDS
from app.agents.vocabulary import terms_for
from app.core.logging import get_logger

log = get_logger(__name__, tag="panel")

#: What a domain match is worth against one turn of silence.
#:
#: Both numbers are guesses and should be read as such. What they encode is an
#: ordering rather than a measurement: relevance beats rotation, but not
#: indefinitely — three turns of silence outweighs a single glancing keyword,
#: which is what stops a founder who talks about money for two minutes hearing
#: only from the CFO.
#:
#: The ratio is the thing to tune when a transcript reads wrong. Raising
#: `DOMAIN_WEIGHT` makes the room more specialised and more repetitive; raising
#: `QUIET_WEIGHT` makes it more evenly distributed and less pointed.
DOMAIN_WEIGHT = 3
QUIET_WEIGHT = 1

#: A turn nobody has spoken in yet counts as this many turns of silence, so an
#: archetype that has never spoken outranks one that spoke a while ago. Without
#: it a panel warms up in declaration order and the third archetype can wait
#: several turns for a first word.
NEVER_SPOKEN = 4


def choose(panel: Sequence[Archetype], context) -> Archetype:
    """The archetype that should take the floor.

    Two signals, both already in the data: whether the answer used vocabulary
    this archetype owns, and how long since they last spoke.

    Deterministic on purpose. A random tiebreak would make a bad transcript
    unreproducible, and the first question about any room is *"why did it ask
    that"*.
    """
    holding = _still_holding(panel, context)
    if holding is not None:
        log.info(
            "panel_kept_the_floor",
            archetype=holding.name,
            words=len(context.said.split()),
        )
        return holding

    ranked = sorted(
        panel,
        key=lambda archetype: (-_score(archetype, context), panel.index(archetype)),
    )
    chosen = ranked[0]

    log.info(
        "panel_routed_by_keyword",
        archetype=chosen.name,
        matched=_domain_hits(chosen, context.said),
        quiet_for=_quiet_for(chosen, context),
    )
    return chosen


def _still_holding(panel: Sequence[Archetype], context) -> Archetype | None:
    """The panelist who keeps the floor, or `None` to rank the room as usual.

    **This exists because the fallback contradicted the prompt it stands in
    for.** `_SELECTION_INSTRUCTION` rule 2 says that a reply carrying no figure,
    no name, no date and no mechanism leaves the floor with the panelist who
    spoke last, to press. Handed exactly that, `choose` did the opposite: with
    no domain vocabulary to weigh, the score collapses to turns of silence and
    the floor goes to whoever has been quiet longest.

    That is the worst available answer to *"I could not place that"*. A room
    which mishears a short utterance should not reply by opening a new line of
    questioning from a new person. Reported 2026-09-19 by way of a missed
    rephrase request: the presenter asked a panelist to put a question another
    way, no pattern in `repeat.py` matched the phrasing, and a stranger
    answered.

    Three conditions, and all of them are needed:

    - **Short.** `repeat.MOST_WORDS`, borrowed rather than invented, because
      the question being asked here is the same one from the other side: could
      this have been a request to hear the question again? Past that cap an
      utterance touching no domain is narrative or an anecdote, and rotating
      through the room is right.
    - **Nothing anybody owns.** A single domain hit anywhere on the panel means
      there is something in it to answer, so §3.1's mixed room applies.
    - **Somebody to keep it.** No panel line yet means no floor to leave where
      it is, on the room's first turn.

    Bounded by #55's dial, which has to be applied here rather than assumed:
    `pressure.presses` is enforced in the selection *prompt*, and this function
    never sees the prompt. Without the check a fallback would quietly exceed
    the dial on exactly the turns where the model failed and nobody is looking.
    """
    if len(context.said.split()) > MOST_WORDS:
        return None
    if any(_domain_hits(archetype, context.said) for archetype in panel):
        return None

    holding = next(
        (archetype for archetype in panel if _quiet_for(archetype, context) == 0),
        None,
    )
    if holding is None:
        return None

    # `presses` is how many times a panelist may press an unanswered question,
    # so one consecutive line is the question itself and the press is the
    # second. Counted from the transcript rather than remembered, for the
    # reason the rest of this module gives: nothing here infers anything.
    if _consecutively(holding, context) > context.pressure.presses:
        return None
    return holding


def _consecutively(archetype: Archetype, context) -> int:
    """Panel lines this archetype has just said in a row, ending at the newest."""
    spoken = [line for line in context.grounding.transcript if line.speaker != USER]

    held = 0
    for line in reversed(spoken):
        if line.speaker != archetype.name:
            break
        held += 1
    return held


def _score(archetype: Archetype, context) -> int:
    return (
        _domain_hits(archetype, context.said) * DOMAIN_WEIGHT
        + _quiet_for(archetype, context) * QUIET_WEIGHT
    )


def _domain_hits(archetype: Archetype, said: str) -> int:
    """How many of this archetype's domains the answer actually used.

    Matched through `vocabulary.terms_for`, not against the canonical name.
    Measured, the canonical name alone routed 7% of realistic utterances: `ARR`
    is revenue, "the team is eight people" is headcount, and "spending more to
    acquire each customer than we make back" is the CFO's whole reason for
    existing while containing none of its words.

    Whole words, so `cost` does not match `costume` and `data` does not match
    `database` — a substring check reads as sophistication and behaves as noise.

    Counted per *domain* rather than per word, so a sentence saying "margin"
    three times is not three times the CFO's. What should raise the score is
    breadth — an answer touching margin *and* cost is more theirs than one
    touching either alone.
    """
    if not archetype.domains:
        return 0

    words = set(re.findall(r"[a-z0-9]+", said.lower()))
    return sum(
        1
        for domain in archetype.domains
        if words.intersection(terms_for(domain))
    )


def _quiet_for(archetype: Archetype, context) -> int:
    """Turns since this archetype last spoke.

    The counterweight to relevance. Without it a founder who talks about money
    for two minutes hears from the CFO and nobody else, which is not a panel — it
    is one person with an audience.
    """
    spoken = [
        line for line in context.grounding.transcript if line.speaker != USER
    ]
    for distance, line in enumerate(reversed(spoken)):
        if line.speaker == archetype.name:
            return distance
    return NEVER_SPOKEN
