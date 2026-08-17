"""The Auditor: the background agent that catches a figure moving.

**`auditor` is the domain term, `audit_log` is the module that records money.**
`CLAUDE.md` names the collision explicitly — colliding the two makes every future
search for either useless — so this lives in `app/agents/` beside the archetypes
it hands the floor to, and never in `app/modules/`.

`docs/auditor-grounding.md` settles what it does. Two jobs had been collapsed
into one word: *grounding* — a challenge tracing to something specific — needs
only that the user said something, and they are speaking claims continuously;
*cross-checking* needs a reference to disagree with, and that is the thing a
deckless session lacks.

So **the transcript is the reference.** A running set of figures the user has
stated, each new one checked against it. Which is what happens in the format
that prompted the question: the sharks have no deck either, and they catch
people because the numbers fail against *each other*.

Deliberately not a fallback for the deckless case. Contradicting yourself is
worth catching whether or not a deck exists, and one Auditor with one code path
avoids a deckless mode that quietly receives less attention than the main one.

**No model here, structurally.** The model's only job is pulling figures out of
speech into a typed claim; every comparison is ordinary code. Arithmetic
hallucination becomes impossible rather than discouraged — and a confidently
wrong number in a panelist's mouth, live, is the one failure the grounding story
cannot survive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.agents.context import Finding
from app.agents.model import TurnUsage
from app.core.errors import FlintroomError
from app.core.logging import get_logger
from app.modules.ingestion.schemas import QuantitativeClaim

log = get_logger(__name__, tag="auditor")


#: How far two figures may differ and still be the same figure, spoken twice.
#:
#: **The single most important number in this module, and it is a guess.**
#: `docs/auditor-grounding.md` makes a false accusation the failure to avoid —
#: *"a panel that pounces on rounding is not intimidating, it is stupid"* — and
#: this is the control. Too tight and the room challenges people for speaking
#: like people; too loose and a figure that genuinely moved goes unremarked.
#:
#: Anchored on the doc's own example: *"About forty then thirty-eight is not a
#: contradiction, it is a person talking"* — 5% apart, and it must not fire. The
#: canonical true positive is a deck saying 61 against a spoken 70, which is 15%
#: apart and must. This sits between them, nearer the safe end, because the two
#: mistakes do not cost the same: a missed catch costs one challenge, a false
#: one costs the room its credibility.
#:
#: Relative rather than absolute, so it means the same thing to a margin and to
#: a revenue figure. A margin moving 2 points from 2% to 4% is a doubling and
#: fires; the same 2 points from 40% to 42% is somebody rounding, and does not.
#: An absolute band would have to be per-unit, per-metric and wrong somewhere.
#:
#: Tune this before tuning anything else in the file. It is the interrupt bar.
ROUNDING_TOLERANCE = 0.08


@dataclass(frozen=True)
class SpokenClaim:
    """A figure the user stated, and when they stated it.

    The claim type is shared with ingestion rather than reinvented, because
    comparing a slide's figure against a spoken one is the Auditor's whole
    function and two types that merely resemble each other cannot be compared.
    `QuantitativeClaim` already carries the unit normalisation and the
    `comparable_to` guard that stops last quarter's revenue reading as a
    contradiction of last year's.

    What differs is the locator — a page number there, an offset into the
    session here — which is exactly why `ExtractedClaim` keeps the page beside
    the claim instead of inside it.
    """

    claim: QuantitativeClaim

    #: Seconds from the start of the interrogation. Part of the evidence, not
    #: bookkeeping: the doc's bar for interrupting a live room is a
    #: contradiction stateable precisely — *both figures, both moments* — and
    #: without the moment the panel is making an accusation the user cannot
    #: check.
    at_seconds: int


def _clock(seconds: int) -> str:
    """`540` as `9:00`, because a panelist says minutes, not seconds."""
    return f"{seconds // 60}:{seconds % 60:02d}"


@dataclass(frozen=True, slots=True)
class ClaimReading:
    """The figures in one utterance, and what reading them cost.

    Text and price together, for the reason `ModelReply` pairs them: the two
    arrive from the same call, and separating them is how a cost gets attributed
    to the wrong turn. `auditor_invocations` is already a column in
    `session_costs` because §4.3 expects this to run per utterance rather than
    once per deck, which is materially more calls than a document diff.

    Empty by default. Most of what a person says in an interrogation carries no
    figure at all, so *nothing here* is the ordinary answer rather than a
    failure.
    """

    claims: tuple[QuantitativeClaim, ...] = ()
    usage: TurnUsage = TurnUsage()


#: Checkable at runtime for the reason `TranscriptionStream` is: there is no
#: base class to inherit and no type checker in the suite, so an adapter that
#: drifted off this seam would stay green everywhere and surface as an Auditor
#: that silently never catches anything. The fake in the tests cannot notice —
#: it conforms by construction, which is precisely how a fake and a real adapter
#: come apart.
@runtime_checkable
class ClaimReader(Protocol):
    """Whatever turns spoken words into typed figures.

    Structural (`Protocol`) like `PanelModel` and `Transcriber`, so an adapter
    is a class that happens to fit rather than one that had to import us.

    **Not called an extraction model, deliberately.** `ingestion` already has an
    `ExtractionModel` and the two are different jobs with opposite requirements:
    that one is batch, latency-insensitive and runs once per deck; this one runs
    inside a live metered room on every utterance. `CLAUDE.md` treats a name
    collision as a real cost — it made `audit_log` and `auditor` distinct for the
    same reason — and two things called extraction would make every search for
    either useless.

    **Its only job is reading.** It never decides what a figure means, whether
    two disagree, or who should say so; every comparison is ordinary code in this
    module. That split is structural rather than stylistic: it makes arithmetic
    hallucination impossible instead of discouraged, and a confidently wrong
    number in a panelist's mouth, live, is the one failure the grounding story
    cannot survive.
    """

    async def read(self, *, said: str) -> ClaimReading:
        """The figures in this utterance, if any.

        **May raise, and the caller survives it.** This is a background
        improvement to a room that already works, so a failure here costs a
        kind of question and never the session.
        """
        ...


@dataclass
class Auditor:
    """One session's running claim set, and what it catches.

    Holds the session and nothing beyond it, like `OrchestratedChannel`'s
    transcript: what a saved session retains is an open product decision, and
    persisting here would answer it by accident in the direction that keeps the
    most data.
    """

    #: Optional, on the same grounds as the speaker: a deployment without one
    #: still transcribes, routes, composes, speaks and captions. It simply never
    #: catches a figure moving, which is a feature absent rather than a room
    #: broken.
    reader: ClaimReader | None = None

    heard: list[SpokenClaim] = field(default_factory=list)

    #: What every reading in this session has cost, accumulated. Reported to
    #: `session_costs` rather than counted by the caller, because only the
    #: adapter knows what the provider charged and only this object sees every
    #: call.
    spent: TurnUsage = TurnUsage()

    #: How many times a reader was actually asked. §4.3 reserves the column, and
    #: a count that is not the number of utterances is the interesting one: it
    #: separates a room where extraction ran from one where it was configured
    #: and silently failing.
    readings: int = 0

    async def listen(self, said: str, *, at_seconds: int) -> Finding | None:
        """Read the figures out of one utterance and check them.

        The moment is stamped here rather than taken from the model. A model
        asked when something was said will answer, plausibly and wrongly, and
        the timestamp is half the evidence a panelist puts to somebody — the
        difference between an accusation and something the user can check.

        **Every failure is swallowed.** The Auditor improves a room that already
        works: the panel challenges what the user said whether or not anything
        was extracted. Letting a reader failure out would settle the session and
        refund it, losing the user the room they came for, over the loss of one
        additional kind of question. Same trade as `select_speaker`, and the
        same reason.
        """
        if self.reader is None:
            return None

        try:
            reading = await self.reader.read(said=said)
        except FlintroomError as refused:
            # `reason` distinguishes a provider that is down from one that is
            # slow, which are different problems with different fixes. Never the
            # utterance — `CLAUDE.md` forbids transcripts in logs.
            log.warning(
                "claim_reading_failed",
                reason=refused.context.get("reason", "unknown"),
            )
            return None

        self.readings += 1
        self.spent = TurnUsage(
            input_tokens=self.spent.input_tokens + reading.usage.input_tokens,
            output_tokens=self.spent.output_tokens + reading.usage.output_tokens,
        )

        # The first catch wins, and the rest of the utterance is still recorded.
        # A panelist interrupts with one contradiction, not a list — and the
        # figures that did not trigger anything are exactly what the next
        # utterance will be checked against.
        caught = None
        for claim in reading.claims:
            found = self.hear(SpokenClaim(claim=claim, at_seconds=at_seconds))
            caught = caught or found
        return caught

    def hear(self, spoken: SpokenClaim) -> Finding | None:
        """Take in one figure, and say whether it contradicts an earlier one.

        Records whatever it is handed, including the contradicting figure. A
        user who revises a number twice has said all three things, and dropping
        the one that caused a finding would make the next check compare against
        a version of the session that never happened.
        """
        caught = self._contradiction(spoken)
        self.heard.append(spoken)
        return caught

    def _contradiction(self, spoken: SpokenClaim) -> Finding | None:
        for earlier in self.heard:
            if _disagrees(earlier, spoken):
                return _finding(earlier, spoken)
        return None


def _disagrees(earlier: SpokenClaim, later: SpokenClaim) -> bool:
    return (
        earlier.claim.metric == later.claim.metric
        and earlier.claim.comparable_to(later.claim)
        and _moved(earlier.claim.value, later.claim.value)
    )


def _moved(before: float, after: float) -> bool:
    """Whether the figure changed, or whether the speaker merely rounded.

    Measured against the larger magnitude, so the answer does not depend on
    which figure was said first. Against the earlier one, a fall from 100 to 90
    and a rise from 90 to 100 would be 10% and 11% — the same disagreement,
    scored differently, and a threshold sitting between them would catch a user
    revising downward while forgiving the identical revision upward.
    """
    if before == after:
        return False

    scale = max(abs(before), abs(after))
    if scale == 0:
        # Both zero is caught above; one zero against the other is a figure
        # appearing or vanishing, which no proportion describes and which is
        # exactly the kind of movement worth putting to somebody.
        return True

    return abs(after - before) / scale > ROUNDING_TOLERANCE


def _finding(earlier: SpokenClaim, later: SpokenClaim) -> Finding:
    """State it precisely enough that the user can check it.

    Both figures and both moments, in the order they were said. The composer is
    handed this verbatim and told to put it to them directly, so a summary that
    cannot be checked is a panelist asserting something is wrong without being
    able to say what.
    """
    return Finding(
        domain=later.claim.metric,
        summary=(
            f"At {_clock(earlier.at_seconds)} they said {_number(earlier.claim)} "
            f"for {earlier.claim.metric}; at {_clock(later.at_seconds)} they said "
            f"{_number(later.claim)}."
        ),
    )


def _number(claim: QuantitativeClaim) -> str:
    """`61.0` as `61`, because a panelist reading it aloud says sixty-one."""
    return f"{claim.value:g}"
