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
