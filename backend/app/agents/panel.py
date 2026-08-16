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

from app.agents.archetypes import Archetype, by_name
from app.agents.model import PanelModel
from app.core.errors import ArchetypeNotFound, PanelTooLarge
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

    #: What the panel has already put to this user in this session.
    #:
    #: Not an optimisation. Without it every archetype re-asks the strongest
    #: question in its strategy, and a room that asks the same thing four times
    #: is not intimidating — it is broken, and obviously so within two minutes.
    asked: tuple[str, ...] = ()


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


@dataclass(frozen=True)
class PanelTurn:
    """What the room says back, and who said it."""

    archetype: Archetype
    line: str

    #: True when the Auditor's finding chose the speaker rather than the model.
    #: Worth carrying because these are the turns the grounding story is judged
    #: on, and *"which challenges were grounded"* should be answerable from the
    #: transcript rather than by re-running anything.
    targeted: bool = False


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
    targeted = archetype is not None

    if archetype is None:
        chosen = await model.select(candidates=panel, context=context)
        archetype = _named(panel, chosen)

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
        targeted=targeted,
        claims=len(context.grounding.claims),
        already_asked=len(context.grounding.asked),
    )
    return PanelTurn(archetype=archetype, line=line, targeted=targeted)


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


def _named(panel: Sequence[Archetype], name: str) -> Archetype:
    """The archetype the model chose, or somebody real if it invented one.

    The selection step returns a string and a model can return any string. This
    runs inside a live, metered room, so raising here does not degrade the
    experience — it ends it, mid-answer, while the user is paying by the minute
    and the panel goes silent for no reason they can see.

    So a name nobody answers to falls back rather than raises. The fallback is
    the first candidate, which is arbitrary and deliberately so: which archetype
    speaks matters far less than that somebody does. It is logged at warning
    because a *steady stream* of these is a prompt that has stopped working, and
    that is worth knowing before the transcripts start reading oddly.
    """
    for archetype in panel:
        if archetype.name == name:
            return archetype

    log.warning("panel_selection_unrecognised", chosen=name, fell_back_to=panel[0].name)
    return panel[0]
