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

from app.agents.archetypes import Archetype
from app.core.logging import get_logger

log = get_logger(__name__, tag="panel")


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
    model,
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
    archetype = _owner(panel, finding.domain) if finding else None
    targeted = archetype is not None

    if archetype is None:
        archetype = _named(panel, await model.select(candidates=panel, context=said))

    # The finding travels to the composer, not just to the routing. An archetype
    # handed the floor because of a contradiction and then not told what the
    # contradiction was produces a challenge that sounds authoritative and cites
    # nothing — Open Risk #2 arriving from the one path meant to cure it.
    line = await model.compose(archetype=archetype, context=said, finding=finding)

    log.info("panel_turn", archetype=archetype.name, targeted=targeted)
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
