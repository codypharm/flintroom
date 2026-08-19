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

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from app.agents.context import Said
from app.core.logging import get_logger
from app.agents.model import TurnUsage
from app.agents.weakness import WeakAnswer

log = get_logger(__name__, tag="debrief")


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


#: Who said a line of the coaching conversation. The user is `USER`, the same
#: constant the room uses, so a transcript line and a coaching turn agree about
#: whose voice is whose.
COACH = "coach"


@dataclass(frozen=True, slots=True)
class Spoken:
    """One line of the coaching conversation — not of the room.

    Deliberately not `Said`. A coaching turn has no `disputed` and no
    `chosen_by`; those describe how a panelist came to speak, and nobody chose
    the coach. Reusing the type would carry two fields that are meaningless here
    and, worse, would make it easy to hand a coaching turn to something
    expecting the room.
    """

    who: str
    text: str


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

    **A turn survives if anything it cites is real.** Invalid citations are
    dropped; a turn left with none becomes the redirect.

    This was the opposite rule for about an hour, and the reversal was measured
    rather than argued. All-must-hold defends against a turn whose first half is
    about the room and whose second half is about the industry — a real shape,
    and the one the fence was written for. What `scripts/coach.py` actually
    observed was different: asked *"did I dodge the time-to-value one?"*, the
    model cited lines 5 and 6, which are exactly right, and then added
    `claim 2` against a session holding one claim. The strict rule threw away a
    correct, kind, useful answer over a hallucinated index on the end — roughly
    one grounded question in five.

    The attack still cannot get through, and that is what made the trade safe.
    A genuine general pitch review has *nothing* in this session to point at, so
    every citation fails and the turn is redirected regardless. Surviving
    requires at least one real anchor in this room, which is what "grounded in
    the session" meant in the first place.

    An uncited turn is not an error and is not logged as one. The most likely
    cause is somebody asking a reasonable question about something this session
    never contained, and the redirect is the honest answer rather than a failure.
    """
    if not held(reply, grounds):
        return REDIRECT
    return reply.text


def held(reply: CoachReply, grounds: Grounds) -> tuple[Cite, ...]:
    """The citations that are really in this session.

    Separate from `spoken` because they are two questions with two callers: the
    user hears text, and anything storing or auditing a coaching turn wants to
    know what it was anchored to. Deriving one from the other later would mean
    checking the same citations twice and being free to disagree.

    A drop is counted rather than passed. The count is the signal that matters —
    a rising rate means the prompt or the numbering has drifted, and the symptom
    at the user's end is a coach that redirects more often for no visible reason.
    Never the citation itself: an index is meaningless without the line it points
    at, and the line is transcript text.
    """
    real = tuple(cite for cite in reply.cites if _is_real(cite, grounds))

    if dropped := len(reply.cites) - len(real):
        log.info("coach_citations_dropped", dropped=dropped, kept=len(real))

    return real


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


#: Checkable at runtime, like every other seam here.
@runtime_checkable
class CoachModel(Protocol):
    """Whatever holds the coaching conversation."""

    async def reply(
        self, *, grounds: Grounds, exchange: Sequence[Spoken]
    ) -> CoachReply:
        """Answer the last thing the user said.

        Sees `grounds` and nothing else about the world. That is the fence's
        first half: the model is not asked to avoid discussing fresh material,
        it is handed a session and asked to talk about it. `spoken` is the
        second half, and the half that holds when the first is jailbroken.

        `exchange` is the coaching conversation so far, ending with the user's
        new turn. Whole rather than summarised, because §3.5 wants follow-ups
        and clarifications — a coach that cannot see what it said two turns ago
        cannot be pushed back on, and answering the same question twice is how a
        conversation stops being one.

        **May raise, and the caller must survive it.** Nothing is live and
        nothing is metered, so a failure costs a retry rather than silence in a
        room. It must arrive as `ProviderUnavailable` without naming the vendor.
        """
        ...

    async def open(self, *, grounds: Grounds) -> CoachReply:
        """Say the first thing, with nothing having been said to you.

        The one turn with no user speech in front of it, which makes it the one
        most able to wander — an opening asked for "how did that go" and handed
        no anchor is exactly the shape that reaches for a general observation
        about pitching, which is the competitor product the wedge refuses. So it
        sees `grounds` and nothing else, like every other turn, and `spoken`
        checks its citations like every other turn. Nothing about being first
        earns an exemption from either half of the fence.

        **What it is for:** putting the ranked list in a human order and saying
        where the room actually got past them. What it is not for is a score.
        `design-guide/coaching_debrief/` opens with a B+ and a delivery read, and
        §1 exists to refuse exactly that — so there is no grade in the reply
        type, no number to render, and nothing here asks for one.

        **May raise, and the caller must survive it.** Same as `reply`: nothing
        is live and nothing is metered, so a failure costs a retry.
        """
        ...

    async def spar(
        self,
        *,
        grounds: Grounds,
        weak: WeakAnswer,
        attempts: Sequence[str],
    ) -> CoachReply:
        """Say what changed between the first answer and this one.

        **Asked what changed, never whether it is good enough.** That is the
        whole of `docs/debrief-and-sparring.md` decision 4, and the reason is an
        asymmetry rather than a preference: false praise sends somebody into the
        real room believing a thin answer landed, so a coach that grades is
        worse than one that does not.

        A comparison is also the shape a model handles well. #43 measured one
        catastrophically failing *"was this good enough?"* — 4 of 4 dodges and
        4 of 4 genuine answers called dodges — and nothing here asks that. Two
        texts and "what is different" is a question with evidence on both sides.

        `attempts` is every go so far, oldest first, ending with the newest.
        Whole rather than only the latest, because "you are further from it than
        you were two tries ago" is a true and useful thing to say, and it cannot
        be said by something holding one string.

        A separate method rather than a flag on `reply`, matching `PanelModel`'s
        two calls: the prompts have different jobs and different failure modes,
        and one method taking a mode would let a caller ask for a coaching turn
        and receive a comparison.
        """
        ...
