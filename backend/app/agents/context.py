"""What a turn is made of.

Data, separated from the behaviour in `panel.py` and `routing.py` because both
operate on it and neither should have to import the other to say so — which is
exactly the circular import that prompted this split.

Nothing here does anything. That is the point: a room's state should be readable
without following a call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.agents.archetypes import Archetype
from app.agents.model import TurnUsage


#: Who said a line. An archetype's `name`, or `USER` for the person being
#: interrogated.
USER = "user"


@dataclass(frozen=True)
class Said:
    """One line of the room, whoever said it.

    A transcript rather than a list of questions, and the difference is not
    cosmetic. Choosing who speaks next turns almost entirely on how the last
    answer *went* — whether it landed, dodged, or opened something up — and
    pressing an evaded question is the single most useful thing a panel does.

    The first version of this carried only the panel's questions, which is half a
    room: a model could see that the CFO had asked about revenue and not whether
    anybody had answered.
    """

    speaker: str
    text: str


@dataclass(frozen=True)
class Grounding:
    """What the room is allowed to attack.

    The whole of the wedge. `CLAUDE.md` refuses to ship interrogation logic that
    cannot cite its source, and Open Risk #2 is that ungrounded generic questions
    kill retention faster than any UI flaw — so a composer that receives only the
    last sentence can produce nothing better than a hard-sounding question about
    a subject it has never seen. That is the competitor product this one exists
    to refuse.

    Claims arrive **pre-rendered as citable lines** rather than as ingestion's
    typed `ExtractedClaim`. It keeps the panel free of the ingestion module and
    keeps the seam one-directional: whoever owns a claim owns how it reads, and
    the panel only ever needs something it can quote back.
    """

    #: What the attached material asserts, one citable line each.
    claims: tuple[str, ...] = ()

    #: The room so far, both sides, in order.
    #:
    #: Both sides because a question without its answer cannot tell a selector
    #: whether to press it. In order because "who has been quiet" is a fact about
    #: position, not about counts.
    #:
    #: The two steps read it differently, and a flat list would make one of them
    #: worse. Selection wants the whole conversation: what was asked, how it was
    #: answered, who has not spoken. Composition wants only what *this* archetype
    #: asked — ten turns in a CFO would otherwise carry six "do not repeat" items,
    #: all about margin, and be steered off the subject it exists to press. A
    #: panelist who stops asking about margin is worse than one who repeats
    #: himself.
    transcript: tuple[Said, ...] = ()

    def asked_by(self, archetype: str) -> tuple[str, ...]:
        """Only what this archetype has already put to them."""
        return tuple(
            line.text for line in self.transcript if line.speaker == archetype
        )


@dataclass(frozen=True)
class TurnContext:
    """Everything the model is allowed to see about this moment.

    One object rather than a widening parameter list, because both steps need
    the same view and the two must never disagree about what happened — a
    selector that knows about the deck and a composer that does not would pick
    the right archetype to say the wrong thing.
    """

    said: str
    grounding: Grounding

    #: Whether `said` is a prefix of a sentence still being spoken.
    #:
    #: Routing runs on the first partial so its ~0.77s hop overlaps the tail of
    #: the utterance — the whole plan for holding the ~1.5s illusion threshold
    #: (Open Risk #3). Composition never does: a panelist answering half a
    #: sentence is not barge-in, it is not listening.
    #:
    #: So this is only ever true for selection, and the reason it has to be said
    #: out loud is that half a sentence and a finished evasion look identical.
    #: Both lack a figure, a name, a date and a mechanism, and the rule that
    #: presses an evasion cannot tell them apart on its own.
    unfinished: bool = False


@dataclass(frozen=True)
class Finding:
    """Something the Auditor caught, and the domain it belongs to.

    The domain is what routes the interruption. `docs/auditor-grounding.md` has
    each derivation pack declare which archetype domain owns a figure, so a
    finding arrives already knowing who should raise it.
    """

    domain: str
    summary: str


#: What decided who speaks. Three paths, and they are not equally good.
#:
#: - `finding` — the Auditor caught a contradiction and the domain that owns the
#:   figure owns the interruption. The best kind of turn there is.
#: - `model` — the ordinary case. Reads the room, sees custom archetypes.
#: - `fallback` — keyword routing, because selection was late, failed, or named
#:   nobody. Measured at 53% relevance, so a turn chosen this way is a turn the
#:   room got roughly half right.
#:
#: Carried on the turn rather than left to be inferred from which log lines
#: appeared, because the failure this exists to expose is silent: a deployment
#: where the model has been erroring for a week looks exactly like a healthy one.
#: The room still speaks, transcripts still read plausibly, and the only symptom
#: is that every choice is coming from the table.
#:
#: `chosen_by=model` over total turns is the health metric.
SelectedBy = Literal["finding", "model", "fallback"]


@dataclass(frozen=True)
class Routed:
    """Who has the floor, how that was decided, and what deciding cost.

    Split out of `interrogate` so the decision can be made somewhere other than
    at the start of the turn. Selection measures 0.77s warm and wants the gist
    of an answer rather than its last word, so the room runs it against a
    partial transcript while the user is still speaking and hands the result in
    when they stop — the shape `docs/panel-orchestration.md` has specified since
    the two-call design was adopted.

    `usage` travels with the choice for the same reason it travels on a turn: the
    provider charged for this call whether or not the answer was used, and a
    caller adding up only what it can see would understate the room in the one
    number §4.3 reconciles against a real invoice.
    """

    archetype: Archetype
    chosen_by: SelectedBy
    usage: TurnUsage = field(default_factory=TurnUsage)


@dataclass(frozen=True)
class PanelTurn:
    """What the room says back, who said it, what chose them, and what it cost."""

    archetype: Archetype
    line: str
    chosen_by: SelectedBy

    #: Both model calls of this turn, summed — routing and composition.
    #:
    #: Carried on the turn rather than counted by the caller because a turn is
    #: the unit that either happened or did not. A caller adding up its own
    #: calls would miss the routing spend on every turn that took the fallback,
    #: and understate the room in the one number §4.3 reconciles against a real
    #: invoice.
    usage: TurnUsage = field(default_factory=TurnUsage)
