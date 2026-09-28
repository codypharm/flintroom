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
from app.agents.difficulty import STANDARD_PRESSURE, Pressure
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

    #: Whether this line opened by taking issue with the previous panelist's
    #: priorities — the turn shape #54 added.
    #:
    #: Here rather than only on `PanelTurn` because the debrief needs it and the
    #: transcript is what the debrief reads. Once written, a disputing line and
    #: an ordinary one are indistinguishable: both are panel text following panel
    #: text. So the question the disputing line moved the room off is, from the
    #: outside, identical to one the presenter simply ducked — and telling
    #: somebody they ducked a question a colleague waved away is both wrong and
    #: reads as the product not having listened.
    #:
    #: The room knows this for certain at the moment it happens, which is the
    #: only moment it is knowable. Reconstructing it later is guesswork.
    #:
    #: Defaults to False so the user's own lines, the Auditor's interruptions and
    #: every existing caller stay unchanged — a dispute is the exception, and an
    #: exception that has to be declared everywhere is one that will be forgotten
    #: somewhere.
    disputed: bool = False

    #: Whether this line is an earlier question of the same panelist's, asked
    #: again in different words because the presenter said they did not follow
    #: it (#117).
    #:
    #: Here for exactly the reason `disputed` is, and against the same failure.
    #: Unmarked, a rephrase and a fresh question are the same shape — panel text
    #: following panel text — so the debrief would find the original question
    #: with no answer after it and rank it as the strongest kind of weak answer,
    #: the one nobody even tried. It would then tell somebody they ducked a
    #: question they had asked to have re-put and then answered.
    #:
    #: Not persisting the rephrase at all was the other option and is worse: the
    #: presenter answers *these* words, and the debrief would grade that answer
    #: against wording they never treated as final.
    rephrasing: bool = False

    #: What handed this speaker the floor, for panel lines. `None` for the user's
    #: own, which nobody chose.
    #:
    #: Carried for the same reason as `disputed`: the debrief reads lines, not
    #: turns. `chosen_by="finding"` is the record that the Auditor caught the
    #: answer *before* this line — the only trace of a contradiction that
    #: survives the room, since nothing persists a `Finding`.
    #:
    #: A stored copy of the finding's own summary was the alternative and is
    #: worse. The line produced by a finding already states the contradiction in
    #: words, grounded in what the user actually said (#45), so a summary beside
    #: it would be a second version of the same fact, free to disagree with the
    #: one the user heard.
    #:
    #: It also gives `SelectedBy`'s health metric somewhere durable to live.
    #: `chosen_by=model` over total turns is what distinguishes a healthy room
    #: from one whose selection model has been erroring for a week, and until now
    #: that existed only in log lines.
    chosen_by: SelectedBy | None = None


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

    #: How hard this room pushes — #55's rung, as two integers.
    #:
    #: Here rather than as a parameter on `select` for the reason this class
    #: exists at all: both steps read one view and must never disagree about
    #: what moment they are in. It also keeps the change off `PanelModel`, so
    #: neither adapter had to learn that calibration exists.
    #:
    #: **Defaults to the room that ships today**, which is what makes "level 2
    #: is byte-identical to what was measured" true by construction. Every
    #: caller that never heard of calibration — the spikes, the older tests,
    #: `scripts/rotation.py` — gets exactly the room those figures describe.
    pressure: Pressure = STANDARD_PRESSURE

    #: What the presenter said about the room they are walking into, or empty.
    #:
    #: #66, and `Product.md` §3.1's permitted substitute for the social-profile
    #: scraping the project refused: *"the user may paste their own text
    #: describing the audience ('my VP hates anything that adds headcount')"*.
    #:
    #: **Here rather than on `Grounding`, and the distinction is the feature.**
    #: `Grounding.claims` are citable — they render under *"Their material
    #: says:"* and a challenge is expected to trace back to one. This is not
    #: citable and must never be quoted, so filing it beside claims would be an
    #: invitation for some later caller to render it as one. It sits beside
    #: `pressure` instead, which is the other room-constant fact the model is
    #: shown: both are true for every turn of a room and neither is evidence.
    #:
    #: The Auditor never sees it. Its reference set is figures, every comparison
    #: is ordinary code, and prose about a colleague is not a claim that can be
    #: contradicted — a note admitted there could "disagree" with the
    #: presenter's own speech and produce exactly the false accusation
    #: `auditor.TOLERANCE` exists to prevent.
    #:
    #: Empty by default, which is the ordinary room. Somebody who did not fill
    #: the box in gets the panel that shipped before this existed.
    audience: str = ""

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

    #: The presenter's opening statement closed without saying what this is
    #: about — under `opening.SUBSTANCE_WORDS`.
    #:
    #: **A fact, never an instruction.** It says what happened; what to do about
    #: it is the composer's, the same discipline `weakness.py` holds for its
    #: annotations and for the reason #43 measured — a model handed a rule
    #: applies it everywhere.
    #:
    #: Only ever true on the first turn of a room. Once somebody has made their
    #: case there is ground to attack, and a panelist still asking what the
    #: company does is one that was not listening.
    thin_opening: bool = False

    #: The earlier question this archetype's first draft repeated, or empty.
    #:
    #: Set only on the one rewrite `panel.interrogate` asks for when a returning
    #: panelist comes back with a question it already put (reported 2026-09-26,
    #: see `agents/reasked.py`). Here rather than as an argument to `compose`
    #: for the reason `thin_opening` is: it stays off `PanelModel`, so neither
    #: adapter nor any fake had to learn it exists.
    #:
    #: **The question itself, not a flag.** The composer already has the list
    #: headed "do not repeat these" and wrote a repeat anyway; told only "not
    #: that" again, it writes the nearest neighbour. Named, it can be told what
    #: to move off.
    repeated: str = ""


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

    #: Whether this turn opened by taking issue with a colleague's priorities.
    #:
    #: Reported so the room can count what it has spent. Derived after the fact
    #: it cannot be: a disputing line and an ordinary one are the same shape, and
    #: a caller inferring one from the text would be reading tea leaves about a
    #: bound that has to be exact.
    disputed: bool = False

    #: Both model calls of this turn, summed — routing and composition.
    #:
    #: Carried on the turn rather than counted by the caller because a turn is
    #: the unit that either happened or did not. A caller adding up its own
    #: calls would miss the routing spend on every turn that took the fallback,
    #: and understate the room in the one number §4.3 reconciles against a real
    #: invoice.
    usage: TurnUsage = field(default_factory=TurnUsage)
