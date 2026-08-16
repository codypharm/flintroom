"""One turn of the room.

Two steps, decided in `docs/panel-orchestration.md`: pick who speaks, then write
that line with **only that archetype's** persona in context. The second half is
the point — a single prompt holding four personas averages them into one voice
wearing four labels, and that failure is invisible from the inside. It reads
perfectly well in a transcript and feels flat in a room.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.agents.archetypes import Archetype, by_name
from app.agents.model import PanelModel
from app.agents.routing import choose
from app.core.errors import ArchetypeNotFound, FlintroomError, PanelTooLarge
from app.core.logging import get_logger
from app.modules.billing.tiers import UPGRADE_LADDER, max_panel_size

log = get_logger(__name__, tag="panel")


def assemble(*, tier: str, chosen: Sequence[str]) -> tuple[Archetype, ...]:
    """The room this caller asked for, if their plan seats it.

    The cap is checked before anything is resolved, so an over-large request is
    refused on the number rather than on whichever name happened to be looked up
    last — the user asked for a room of five, and "we could not find X" would be
    an answer to a question they did not ask.

    A name nobody in the library answers to is refused rather than skipped.
    Dropping it silently would seat a smaller room than the user assembled, and
    they would find out by noticing somebody never spoke.
    """
    if len(chosen) > max_panel_size(tier):
        raise PanelTooLarge(_too_large_message(tier, len(chosen)), tier=tier, asked=len(chosen))

    panel = []
    for name in chosen:
        archetype = by_name(name)
        if archetype is None:
            raise ArchetypeNotFound(archetype=name)
        panel.append(archetype)

    return tuple(panel)


def _too_large_message(tier: str, asked: int) -> str:
    """State the cap, then name the plan that would take it.

    The tone `MaterialTooLarge` fixed: the user's number, our number, and the
    cheapest tier that would accept it. No apology and no verb of persuasion —
    the upgrade is an available fact and the client renders the button.
    """
    seats = max_panel_size(tier)
    upgrade = next(
        (
            name
            for name in UPGRADE_LADDER
            if max_panel_size(name) >= asked
        ),
        None,
    )
    said = f"Your plan seats {seats} panelists."
    return f"{said} {upgrade.title()} seats {max_panel_size(upgrade)}." if upgrade else said


@dataclass(frozen=True)
class Asked:
    """A question the room has already put, and who put it.

    The attribution is what lets the two steps see different views of the same
    history — panel-wide for selection, this archetype only for composition.
    Without it both get a flat list and one of them is wrong.
    """

    archetype: str
    question: str


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

    #: What the room has already put to this user, attributed.
    #:
    #: Not an optimisation. Without it every archetype re-asks the strongest
    #: question in its strategy, and a room that asks the same thing four times
    #: is not intimidating — it is broken, and obviously so within two minutes.
    #:
    #: Attributed rather than flat, because the two steps need opposite views and
    #: a flat list makes one of them worse. Selection wants the whole room: who
    #: has been quiet and what ground is covered is what decides who speaks next.
    #: Composition wants this archetype alone — a CFO ten turns in would otherwise
    #: carry six "do not repeat" items, all about margin, and be steered off the
    #: subject it exists to press. A panelist who stops asking about margin is
    #: worse than one who repeats himself.
    asked: tuple[Asked, ...] = ()

    def asked_by(self, archetype: str) -> tuple[str, ...]:
        """Only what this archetype has already put to them."""
        return tuple(
            entry.question for entry in self.asked if entry.archetype == archetype
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
class PanelTurn:
    """What the room says back, who said it, and what chose them."""

    archetype: Archetype
    line: str
    chosen_by: SelectedBy


async def interrogate(
    panel: Sequence[Archetype],
    *,
    said: str,
    model: PanelModel,
    grounding: Grounding | None = None,
    finding: Finding | None = None,
) -> PanelTurn:
    """Answer one thing the user said, in one archetype's voice.

    One speaker, not a chorus. A room where everybody responds to everything is
    not a room, and it is also four times the cost of one where somebody is in
    charge of the floor.

    **A finding routes itself.** §3.3 assigns the interrupter by domain — *"the
    CFO catches the margin contradiction, not the Technical Skeptic"* — so when
    the Auditor has caught something the speaker is already determined. Asking a
    model to re-derive that spends a hop on a lookup and adds a way to get it
    wrong, and getting it wrong reads as a panel that is not listening.
    """
    context = TurnContext(said=said, grounding=grounding or Grounding())

    archetype = _owner(panel, finding.domain) if finding else None
    chosen_by: SelectedBy = "finding"

    if archetype is None:
        archetype, chosen_by = await _speaker(panel, context, model)

    # The finding travels to the composer, not just to the routing. An archetype
    # handed the floor because of a contradiction and then not told what the
    # contradiction was produces a challenge that sounds authoritative and cites
    # nothing — Open Risk #2 arriving from the one path meant to cure it.
    line = await model.compose(archetype=archetype, context=context, finding=finding)

    # Never the line itself, and never a claim. Ingested material contents are
    # forbidden in logs (CLAUDE.md) and a panelist's line quotes them directly —
    # counts say everything an operator needs and disclose nothing.
    log.info(
        "panel_turn",
        archetype=archetype.name,
        chosen_by=chosen_by,
        claims=len(context.grounding.claims),
        already_asked=len(context.grounding.asked),
    )
    return PanelTurn(archetype=archetype, line=line, chosen_by=chosen_by)


async def _speaker(
    panel: Sequence[Archetype], context: TurnContext, model: PanelModel
) -> tuple[Archetype, SelectedBy]:
    """Who takes the floor when the Auditor has not decided it.

    A model, because keyword routing measured 53% relevance against real speech
    and is blind to custom archetypes — a persona somebody wrote this morning is
    in no vocabulary table, so it could never be chosen for relevance. Pro sells
    those; routing that cannot see them is not routing.

    The call costs ~0.8s and is meant to run against a partial transcript while
    the user is still speaking, so it lands before the turn needs it.

    **Every failure falls through to keywords rather than up to the caller.** A
    slow model, a 502, a name nobody answers to — all of them end with somebody
    speaking. This is a live metered room, and a pause with nobody in it is the
    failure a user notices first while paying by the minute.
    """
    try:
        chosen = await model.select(candidates=panel, context=context)
    except FlintroomError as refused:
        # `reason` distinguishes a provider that is down from one that is slow,
        # which are different problems with different fixes.
        log.warning(
            "panel_selection_failed",
            reason=refused.context.get("reason", "unknown"),
            panel=len(panel),
        )
        return choose(panel, context), "fallback"

    for archetype in panel:
        if archetype.name == chosen:
            return archetype, "model"

    # Logged with what it actually said. A steady stream of these is a prompt
    # that has stopped working, and the name it returned is the only clue.
    log.warning("panel_selection_unrecognised", chosen=chosen, panel=len(panel))
    return choose(panel, context), "fallback"


def _owner(panel: Sequence[Archetype], domain: str) -> Archetype | None:
    """Whoever owns this domain, or nobody.

    `None` rather than a fallback, deliberately: an unowned domain means the
    finding is real but this panel has no natural voice for it, and the honest
    answer is to let the ordinary selection step run. Forcing it on somebody
    produces the *"engineer challenges the margin"* failure this routing exists
    to prevent.
    """
    for archetype in panel:
        if domain in archetype.domains:
            return archetype
    return None
