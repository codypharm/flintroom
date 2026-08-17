"""The coach, and the fence around what it may talk about.

`Product.md` §3.5 makes this the part users pay for: *"the interrogation creates
the problem; this solves it."* §405 and `CLAUDE.md` then draw a line that is easy
to state and easy to get wrong — **the coach is conversational in manner and
bounded in subject.**

Conversational is not a concession. Follow-ups, clarifications, pushing back on
a thin re-answer: §3.5 asks for *"a conversational debrief, not a static
dashboard"*, and reducing it to form-filling would lose the phase its value.

Bounded is the part that has to be built rather than asked for. An unscoped
coach hands every user unlimited free pitch review and removes the reason to pay
for the panel, and open-ended *"listen and tell me how I did"* is precisely the
competitor product §1 exists to refuse.

**The bound is the output shape, not a prompt.** `CLAUDE.md`: a prompt saying
"don't do general pitch review" is one jailbreak from failing, and users will
try. Every turn names the artefact it is grounded in; code checks that artefact
is really there. A general review of fresh material cannot cite a line of a room
it never happened in, so the constraint holds without the model policing itself
— and #43 measured what happens when a model is asked to police itself.

What this module does not do is hold the conversation. It decides what may be
said, and `coach_models/` says it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.agents.context import Said
from app.agents.model import TurnUsage
from app.agents.weakness import WeakAnswer


#: What the coach says instead, when a turn is grounded in nothing.
#:
#: **A product moment, never a paywall** — `CLAUDE.md` says so twice, and it is a
#: metering promise rather than a courtesy. The coach is unmetered, so refusing
#: to review fresh material withholds nothing that was paid for; it names which
#: room the work belongs in. A redirect that mentioned upgrading would turn the
#: free phase into an upsell surface and make "unlimited coaching" read as bait.
#:
#: Phrased as an offer rather than a refusal. The user asked for something
#: reasonable and the honest answer is that the product does it properly
#: somewhere else.
REDIRECT = (
    "That's what the room is for — I can only work from the session we just "
    "had. Start a new room and I'll have something real to take apart."
)


@dataclass(frozen=True, slots=True)
class Cite:
    """One thing a coaching turn is grounded in.

    Tagged rather than a bare integer, because the three grounds §405 names are
    different collections and an index into the wrong one is not a citation. A
    single number would also make the two indistinguishable at the point where
    it matters most — a turn "citing line 4" against a deck with four claims and
    a room with forty lines.

    `finding` is not a kind of its own: a weak answer already carries the
    transcript ordinal of the question it is about, so citing that question
    cites the finding. One key, one meaning.
    """

    kind: Literal["line", "claim"]
    index: int


@dataclass(frozen=True)
class Grounds:
    """Everything the coach is allowed to have an opinion about.

    §405, exactly: the session transcript, ranked weak answers, Auditor findings
    and ingested material. This is handed to the model as its whole world and is
    also what a citation is checked against, which is the property that makes the
    fence structural — the same object bounds what it sees and what it may claim
    to have seen.
    """

    transcript: tuple[Said, ...] = ()

    #: What the room got wrong, worst first — the artefact #57 stores.
    weak_answers: tuple[WeakAnswer, ...] = ()

    #: The attached material, pre-rendered as citable lines, exactly as the panel
    #: receives them. Same shape on both sides of the session so a claim reads
    #: identically to whoever quotes it.
    claims: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoachReply:
    """What the model wants to say, before anything is believed.

    Separate from what the user hears, deliberately. This is a claim about the
    session; `spoken` decides whether it survives checking. Collapsing the two
    would leave nothing in the type system between the model's output and the
    user's ear.
    """

    text: str
    cites: tuple[Cite, ...] = ()
    usage: TurnUsage = field(default_factory=TurnUsage)


def spoken(reply: CoachReply, grounds: Grounds) -> str:
    """What the user actually hears.

    **Every citation must hold, not merely one.** A check satisfied by any single
    valid citation is trivially defeated: name a real line, then say anything.
    That is the shape a model would land on without meaning to — the first half
    of a sentence is about the room and the second half is about the industry —
    and it is exactly the drift the fence exists to catch.

    An uncited turn is not an error and is not logged as one. The most likely
    cause is a user asking a reasonable question about something this session
    never contained, and the honest response is the redirect rather than a
    failure.
    """
    if not reply.cites:
        return REDIRECT
    if not all(_is_real(cite, grounds) for cite in reply.cites):
        return REDIRECT
    return reply.text


def _is_real(cite: Cite, grounds: Grounds) -> bool:
    """Whether the thing cited is in this session.

    An ordinal is cheap to produce — any integer in range looks plausible — so
    this is the same check `weakness.verified` makes for the same reason: a claim
    about this room is checkable against this room, and nothing else in the
    pipeline is in a position to notice.
    """
    if cite.kind == "line":
        return 0 <= cite.index < len(grounds.transcript)
    if cite.kind == "claim":
        return 0 <= cite.index < len(grounds.claims)
    return False
