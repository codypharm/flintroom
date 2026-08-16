"""One turn of the room.

The types a turn is made of live in `context.py`; they are re-exported here
because `interrogate` is the thing callers reach for and its inputs should not
require a second import to find.

Two steps, decided in `docs/panel-orchestration.md`: pick who speaks, then write
that line with **only that archetype's** persona in context. The second half is
the point — a single prompt holding four personas averages them into one voice
wearing four labels, and that failure is invisible from the inside. It reads
perfectly well in a transcript and feels flat in a room.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.agents.archetypes import Archetype, by_name
from app.agents.context import (
    USER,
    Finding,
    Grounding,
    PanelTurn,
    Said,
    SelectedBy,
    TurnContext,
)
from app.agents.model import PanelModel
from app.agents.routing import choose
from app.core.errors import (
    ArchetypeNotFound,
    DuplicatePanelist,
    FlintroomError,
    PanelTooLarge,
)
from app.core.logging import get_logger
from app.modules.billing.tiers import UPGRADE_LADDER, max_panel_size

log = get_logger(__name__, tag="panel")


def assemble(*, tier: str, chosen: Sequence[str]) -> tuple[Archetype, ...]:
    """The room this caller asked for, if their plan seats it.

    The cap is checked before anything is resolved, so an over-large request is
    refused on the number rather than on whichever name happened to be looked up
    last — the user asked for a room of five, and "we could not find X" would be
    an answer to a question they did not ask.

    A name nobody in the library answers to is refused rather than skipped, and
    a name given twice is refused rather than deduped. Both would otherwise seat
    a smaller room than the user assembled, and they would find out by noticing
    somebody never spoke.
    """
    if len(chosen) > max_panel_size(tier):
        raise PanelTooLarge(_too_large_message(tier, len(chosen)), tier=tier, asked=len(chosen))

    panel = []
    for name in chosen:
        archetype = by_name(name)
        if archetype is None:
            raise ArchetypeNotFound(archetype=name)
        if archetype in panel:
            raise DuplicatePanelist(archetype=name)
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
        turns_so_far=len(context.grounding.transcript),
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
