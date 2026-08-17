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
from app.agents.dispute import contested
from app.agents.context import (
    USER,
    Finding,
    Grounding,
    PanelTurn,
    Routed,
    Said,
    SelectedBy,
    TurnContext,
)
from app.agents.model import PanelModel, TurnUsage
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
    routed: Routed | None = None,
    disputes_spent: int = 0,
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

    `routed` is a choice already made — by a room that ran `select_speaker`
    against a partial transcript while the user was still talking, so the 0.77s
    it costs is spent inside the utterance rather than after it. Passed in
    rather than fetched, because only the caller owning the loop knows when a
    partial arrived. Without one this routes here, as it always did, and every
    caller that is not a live room still works unchanged.

    A finding still outranks it: the Auditor catching a contradiction is a
    better reason to hand somebody the floor than a guess made three seconds ago
    on half a sentence.
    """
    context = TurnContext(said=said, grounding=grounding or Grounding())

    archetype = _owner(panel, finding.domain) if finding else None
    chosen_by: SelectedBy = "finding"
    # A pre-routed choice still carries what it cost even when a finding
    # overrules it. The provider charged for that call the moment it was made,
    # and dropping the tokens here would understate exactly the rooms where the
    # Auditor is doing its job.
    routing = routed.usage if routed else TurnUsage()

    if archetype is None and routed is not None:
        archetype, chosen_by = routed.archetype, routed.chosen_by

    if archetype is None:
        chosen = await select_speaker(panel, context=context, model=model)
        archetype, chosen_by, routing = chosen.archetype, chosen.chosen_by, chosen.usage

    # The finding travels to the composer, not just to the routing. An archetype
    # handed the floor because of a contradiction and then not told what the
    # contradiction was produces a challenge that sounds authoritative and cites
    # nothing — Open Risk #2 arriving from the one path meant to cure it.
    # Decided here rather than inside the composer, because it is an occasion
    # and not a judgement — `app/agents/dispute.py` says why at length. A
    # finding outranks it: the Auditor catching a contradiction is a better use
    # of a turn than a difference of emphasis, and a line doing both would do
    # neither clearly.
    dispute = (
        None if finding else contested(archetype, panel, context, spent=disputes_spent)
    )

    written = await model.compose(
        archetype=archetype, context=context, finding=finding, dispute=dispute
    )

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
    return PanelTurn(
        archetype=archetype,
        line=written.text,
        chosen_by=chosen_by,
        disputed=dispute is not None,
        # Routing plus composition. A turn that fell back to keywords still
        # carries whatever the failed routing call cost, because the provider
        # charged for it either way.
        usage=TurnUsage(
            input_tokens=routing.input_tokens + written.usage.input_tokens,
            output_tokens=routing.output_tokens + written.usage.output_tokens,
        ),
    )


async def select_speaker(
    panel: Sequence[Archetype], *, context: TurnContext, model: PanelModel
) -> Routed:
    """Who takes the floor when the Auditor has not decided it.

    A model, because keyword routing measured 53% relevance against real speech
    and is blind to custom archetypes — a persona somebody wrote this morning is
    in no vocabulary table, so it could never be chosen for relevance. Pro sells
    those; routing that cannot see them is not routing.

    Measured warm at 0.77s. **Public because that cost is only affordable if
    somebody else decides when to pay it** — a live room calls this against a
    partial transcript while the user is still speaking, so the hop overlaps the
    tail of the utterance instead of standing between it and the answer.
    `context.said` is therefore often an unfinished sentence, which is what this
    call was always meant to work from: it needs the gist and the room, not the
    last word.

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
        # No usage: the call raised, so nothing was returned to read it off. A
        # provider that charged for a failed request undercounts here, which is
        # the safe direction to be wrong in and worth knowing about.
        return Routed(choose(panel, context), "fallback")

    for archetype in panel:
        if archetype.name == chosen.text:
            return Routed(archetype, "model", chosen.usage)

    # Logged with what it actually said. A steady stream of these is a prompt
    # that has stopped working, and the name it returned is the only clue.
    log.warning("panel_selection_unrecognised", chosen=chosen.text, panel=len(panel))
    return Routed(choose(panel, context), "fallback", chosen.usage)


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
