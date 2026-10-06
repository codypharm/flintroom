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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from app.agents.archetypes import Archetype, by_name
from app.agents.authored import is_authored
from app.agents.difficulty import STANDARD_PRESSURE, Pressure
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
from app.agents.model import ModelReply, PanelModel, TurnUsage
from app.agents.reasked import already_asked
from app.agents.routing import choose
from app.core.errors import (
    ArchetypeNotFound,
    DuplicatePanelist,
    FlintroomError,
    PanelTooLarge,
    PanelWithoutAShippedVoice,
)
from app.core.logging import get_logger
from app.modules.billing.tiers import UPGRADE_LADDER, max_panel_size

log = get_logger(__name__, tag="panel")


def assemble(
    *,
    tier: str,
    chosen: Sequence[str],
    authored: Mapping[str, Archetype] | None = None,
) -> tuple[Archetype, ...]:
    """The room this caller asked for, if their plan seats it.

    The cap is checked before anything is resolved, so an over-large request is
    refused on the number rather than on whichever name happened to be looked up
    last — the user asked for a room of five, and "we could not find X" would be
    an answer to a question they did not ask.

    A name nobody in the library answers to is refused rather than skipped, and
    a name given twice is refused rather than deduped. Both would otherwise seat
    a smaller room than the user assembled, and they would find out by noticing
    somebody never spoke.

    **`authored` is how rows get in, and the caller loads them.** This function
    stays synchronous and free of a database, which is what keeps it testable
    against a plain dict and keeps `agents/` from importing a session — the same
    property `composition.compose()` has and the reason a custom archetype can
    never be seated automatically. A `custom:` name absent from the mapping is a
    caller that forgot to load it, and `by_name` raises rather than letting the
    user be told their own panelist does not exist.

    The floor is checked last, after every name has resolved. A room that is
    both all-authored and contains a typo should hear about the typo: it is the
    more actionable of the two, and answering the rule first costs a second
    round trip to learn about the first.
    """
    if len(chosen) > max_panel_size(tier):
        raise PanelTooLarge(_too_large_message(tier, len(chosen)), tier=tier, asked=len(chosen))

    rows = authored or {}
    panel: list[Archetype] = []
    for name in chosen:
        # An authored name never falls through to the shipped library, and the
        # distinction is one a test found rather than one I designed. `by_name`
        # raises on the prefix because a caller that forgot to load a row is a
        # defect — but a row absent *after* the loader ran is not a defect at
        # all. It is somebody asking for a panelist that is not theirs, or one
        # they retired, and the honest answer is the same as for a typo.
        #
        # It is also what keeps the ownership check quiet: `seatable` is scoped
        # to the owner, so another account's panelist is simply not found, and
        # nothing here confirms that the row exists.
        archetype = (
            rows.get(name) if is_authored(name) else rows.get(name) or by_name(name)
        )
        if archetype is None:
            raise ArchetypeNotFound(archetype=name)
        if archetype in panel:
            raise DuplicatePanelist(archetype=name)
        panel.append(archetype)

    if panel and all(is_authored(one.name) for one in panel):
        raise PanelWithoutAShippedVoice()

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
    pressure: Pressure = STANDARD_PRESSURE,
    audience: str = "",
    thin_opening: bool = False,
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

    `pressure` is #55's rung — how many times a panelist may press an
    unanswered question, and how often the room may talk over itself. It is
    stamped onto the context here because this is where the context is built,
    and it defaults to the room that ships today so that every caller which has
    never heard of calibration gets exactly the room `scripts/rotation.py`
    measured.

    `audience` is #66 — what the presenter wrote about the room they are
    walking into. Stamped here with `pressure` and for the same reasons: it is
    true of the whole room rather than of this moment, and it defaults to empty
    so that every caller predating it gets the ungrounded-in-that-respect room
    it already had. It reaches the composer fenced as data and is never spoken.
    """
    context = TurnContext(
        said=said,
        grounding=grounding or Grounding(),
        pressure=pressure,
        audience=audience,
        # Only ever true on a room's first turn — #79. Stamped here with
        # `pressure` because this is where the context is built, and it stays
        # off `PanelModel` for the same reason calibration did: neither adapter
        # has to learn that an opening floor exists.
        thin_opening=thin_opening,
    )

    taking = who_takes_the_floor(panel, finding=finding, routed=routed)
    # A pre-routed choice still carries what it cost even when a finding
    # overrules it. The provider charged for that call the moment it was made,
    # and dropping the tokens here would understate exactly the rooms where the
    # Auditor is doing its job.
    routing = routed.usage if routed else TurnUsage()

    if taking is None:
        chosen = await select_speaker(panel, context=context, model=model)
        archetype, chosen_by, routing = chosen.archetype, chosen.chosen_by, chosen.usage
        superseded = False
    else:
        archetype, chosen_by = taking.archetype, taking.chosen_by
        superseded = taking.superseded

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
    spent = [written.usage]

    # A panelist returning to the floor with a question it already put — the
    # 2026-09-26 report. Checked in code because the prompt already forbids it
    # and that did not hold. A finding is exempt: it is new evidence, and §3.3
    # gives it to the domain's owner and nobody else.
    repeated = None if finding else _repeating(archetype, context, written.text)
    if repeated is not None:
        redrawn = await _not_again(panel, archetype, context, model, repeated, dispute)
        archetype, written, dispute = redrawn.archetype, redrawn.written, redrawn.dispute
        chosen_by = redrawn.chosen_by or chosen_by
        spent.extend(redrawn.spent)

    # Never the line itself, and never a claim. Ingested material contents are
    # forbidden in logs (CLAUDE.md) and a panelist's line quotes them directly —
    # counts say everything an operator needs and disclose nothing.
    log.info(
        "panel_turn",
        archetype=archetype.name,
        chosen_by=chosen_by,
        # #75. Whether the Auditor's catch handed the floor to somebody *other*
        # than the early routing had picked — which is the rate at which the
        # screen's emerging tray has to swap under a presenter's eye.
        #
        # A log field rather than a column, because it is a fact about how the
        # room behaves rather than about what was said: an operator counts it,
        # the debrief has no use for it, and a migration to answer a design
        # question is a migration to carry forever. `chosen_by` cannot answer
        # it — a finding that agrees with the routing and one that overrules it
        # are the same value.
        superseded=superseded,
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
        # A draft sent back still cost what the provider charged for it.
        usage=TurnUsage(
            input_tokens=routing.input_tokens + sum(u.input_tokens for u in spent),
            output_tokens=routing.output_tokens + sum(u.output_tokens for u in spent),
        ),
    )


def _closed(archetype: Archetype, context: TurnContext) -> tuple[str, ...]:
    """The questions this panelist may not put again on this turn.

    All of them, except that a panelist speaking straight after its own
    question may press *that* one — #55's dial exists precisely so that it can.

    Only that one. The press used to exempt the whole turn, and reported
    2026-10-06 is what that allowed: a panelist holding the floor asked,
    asked something else, then asked the first question again. Every turn was
    a press, so nothing was ever checked.
    """
    asked = context.grounding.asked_by(archetype.name)
    spoken = [line for line in context.grounding.transcript if line.speaker != USER]
    if spoken and spoken[-1].speaker == archetype.name:
        return asked[:-1]
    return asked


def _repeating(archetype: Archetype, context: TurnContext, line: str) -> str | None:
    """The question this line repeats, or `None` if it may be said."""
    return already_asked(line, _closed(archetype, context))


@dataclass(frozen=True, slots=True)
class _Redrawn:
    """What the turn became after its first draft came back as a repeat."""

    archetype: Archetype
    written: ModelReply
    dispute: Said | None
    #: Set only when the floor changed hands, and then to `fallback`: code
    #: overruled the model's pick, which is what that value already means.
    chosen_by: SelectedBy | None
    spent: list[TurnUsage] = field(default_factory=list)


async def _not_again(
    panel: Sequence[Archetype],
    archetype: Archetype,
    context: TurnContext,
    model: PanelModel,
    repeated: str,
    dispute: Said | None,
) -> _Redrawn:
    """One rewrite, told which question it repeated; then somebody else.

    **Bounded at two extra calls, and usually one.** Each is a composition,
    measured at 0.82s, so the worst case adds about 1.6s to a turn that Open
    Risk #3 budgets at 1.5s. That is only paid on a turn that was about to
    repeat itself, which is the one turn where the room had already lost the
    illusion.

    **The screen can be wrong for a beat when the floor moves.** #75 announces
    the next speaker before this runs, from `who_takes_the_floor`, and nothing
    here can reach back and change it. The announced tray emerges, and clears
    the moment the real voice arrives. A tray shown for a second under the wrong
    portrait was judged cheaper than a panelist asking the same thing twice,
    and `panel_repeat_caught` with `outcome=handed_off` is how often it happens.
    """
    earlier = _closed(archetype, context)
    rewrite = await model.compose(
        archetype=archetype,
        context=replace(context, repeated=repeated),
        dispute=dispute,
    )
    if already_asked(rewrite.text, earlier) is None:
        log.info("panel_repeat_caught", archetype=archetype.name, outcome="rewritten")
        return _Redrawn(archetype, rewrite, dispute, None, [rewrite.usage])

    others = [one for one in panel if one.name != archetype.name]
    if not others:
        # A panel of one has nobody to hand to. A repeat is better than silence
        # in a metered room.
        log.info("panel_repeat_caught", archetype=archetype.name, outcome="kept")
        return _Redrawn(archetype, rewrite, dispute, None, [rewrite.usage])

    # The keyword router, which is deterministic and costs nothing. A second
    # selection call would be another 0.77s to decide something the room only
    # needs to be roughly right about: anybody but the panelist who has run out.
    taker = choose(others, context)
    handed = await model.compose(archetype=taker, context=context)
    log.info(
        "panel_repeat_caught",
        archetype=archetype.name,
        outcome="handed_off",
        to=taker.name,
    )
    # No dispute travels. It was an occasion for the panelist who is not now
    # speaking, and `dispute.py` counts what a room spends on them.
    return _Redrawn(taker, handed, None, "fallback", [rewrite.usage, handed.usage])


@dataclass(frozen=True, slots=True)
class TakingTheFloor:
    """Who speaks next, how that was decided, and whether it changed."""

    archetype: Archetype
    chosen_by: SelectedBy
    #: Whether a finding overruled a *different* archetype that early routing
    #: had already picked — #75. False when there was nothing to overrule, and
    #: false when the Auditor happened to agree.
    superseded: bool


def who_takes_the_floor(
    panel: Sequence[Archetype],
    *,
    finding: Finding | None,
    routed: Routed | None,
) -> TakingTheFloor | None:
    """The floor, decided from what is already in hand. No model call.

    Extracted from `interrogate` for #75, and the extraction is the point rather
    than tidiness. The live screen announces who is about to challenge roughly
    1.2s before they are audible — composition is 0.82s and synthesis 0.38s —
    and an announcement derived from a second reading of this rule would be free
    to disagree with the speaker who then arrives. A tray that develops for
    somebody who never speaks has lied to a presenter mid-argument, which is
    exactly why #75 was split out of #41 rather than built with it.

    So there is one spelling, `interrogate` uses it, and the room announces from
    the same call.

    `None` when neither input decides it — no finding, and no early routing —
    which is an utterance that produced no partial for `_route` to start on.
    The caller then routes inline, as it always did, and the screen announces
    nothing rather than guessing.

    **A finding outranks routing**, which is §3.3's rule: the Auditor catching a
    contradiction assigns the interrupter by domain, so asking a model to
    re-derive it spends a hop on a lookup and adds a way to be wrong. But a
    finding whose domain nobody at this table owns decides nothing, and falls
    through to whoever routing picked.
    """
    caught = _owner(panel, finding.domain) if finding else None

    if caught is not None:
        return TakingTheFloor(
            archetype=caught,
            chosen_by="finding",
            # Compared rather than assumed. Until #75 `routed` was discarded
            # unread whenever a finding existed, so "the Auditor decided" and
            # "the Auditor overruled somebody" were the same record — and the
            # rate of the second is the thing the screen's swap depends on.
            superseded=routed is not None and routed.archetype.name != caught.name,
        )

    if routed is not None:
        return TakingTheFloor(
            archetype=routed.archetype, chosen_by=routed.chosen_by, superseded=False
        )

    return None


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
