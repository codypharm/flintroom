"""A panel taking a turn.

`docs/panel-orchestration.md` settles the shape: pick a speaker, then write that
archetype's line with only their persona in context. What these tests hold is the
part that decides whether four archetypes sound like four people or like one
model wearing four labels.

No model is called. `mocking.md` allows a fake at the vendor boundary, and that is
exactly where this one sits — what is under test is the loop around it.
"""

from __future__ import annotations

from app.agents.panel import Finding, interrogate
from app.agents.archetypes import DEFAULT_PANEL


class FakePanelModel:
    """A model that answers what it was told to, and remembers what it was asked."""

    def __init__(self, *, selects: str, writes: str = "Where does that number come from?") -> None:
        self._selects = selects
        self._writes = writes
        self.asked_to_write_as: list[str] = []
        self.composed_with: list[tuple] = []

    async def select(self, *, candidates, context) -> str:
        return self._selects

    async def compose(self, *, archetype, context, finding=None) -> str:
        self.asked_to_write_as.append(archetype.name)
        self.composed_with.append((context, finding))
        return self._writes


async def test_the_panel_answers_in_one_archetypes_voice():
    """The tracer bullet: an answer goes in, one panelist speaks.

    One archetype, not a chorus. The whole reason turn-taking is a decision at
    all is that a room where everybody responds to everything is not a room.
    """
    model = FakePanelModel(selects="margin_hawk", writes="Your margin assumes no churn.")

    turn = await interrogate(
        DEFAULT_PANEL, said="We hold 61% gross margin at scale.", model=model
    )

    assert turn.archetype.name == "margin_hawk"
    assert turn.line == "Your margin assumes no churn."


async def test_a_model_that_names_nobody_in_the_room_does_not_kill_the_session():
    """The selection step returns a string, and a model can return any string.

    This is a live, metered room. `CLAUDE.md` forbids interrupting one, and an
    exception here would do worse than interrupt it — the user is mid-answer,
    paying by the minute, and the panel simply stops. A hallucinated name is not
    a rare event to design against later; it is a Tuesday.

    Falling back to a real archetype keeps the room running. Which one barely
    matters next to the fact that somebody speaks.
    """
    model = FakePanelModel(selects="the_ghost_of_warren_buffett")

    turn = await interrogate(
        DEFAULT_PANEL, said="We hold 61% gross margin at scale.", model=model
    )

    assert turn.archetype in DEFAULT_PANEL
    assert model.asked_to_write_as == [turn.archetype.name]


class RefusesToSelect(FakePanelModel):
    """A model that fails if the selection step is reached at all."""

    async def select(self, *, candidates, context) -> str:
        raise AssertionError("asked a model to route a finding that routes itself")


async def test_a_finding_is_taken_by_the_archetype_whose_domain_owns_it():
    """§3.3: the CFO catches the margin contradiction, not the Technical Skeptic.

    No model is consulted, and that is the design rather than an optimisation.
    `docs/auditor-grounding.md` has each derivation pack declare which archetype
    domain owns a figure, so by the time a finding exists the interrupter is
    already determined — asking a model to re-derive it spends a hop on a lookup
    and introduces a way to get it wrong.

    Getting this wrong is not cosmetic. A panel where the engineer challenges the
    margin reads as a panel that is not listening, which is Open Risk #2 arriving
    by a different route.
    """
    model = RefusesToSelect(selects="unused", writes="Margin was 61% on slide four.")

    turn = await interrogate(
        DEFAULT_PANEL,
        said="Our margin is about 70%.",
        finding=Finding(domain="margin", summary="Slide 4 says 61%."),
        model=model,
    )

    assert turn.archetype.name == "margin_hawk"


async def test_the_interrupting_archetype_is_told_what_was_caught():
    """Targeted but ungrounded is the worst of both.

    `CLAUDE.md`: *"do not ship interrogation logic that can't cite its source."*
    An archetype handed the floor because of a contradiction, and then not told
    what the contradiction was, produces a challenge that sounds authoritative
    and cites nothing — which is Open Risk #2 exactly, arriving from the one path
    that was supposed to be the cure for it.
    """
    model = FakePanelModel(selects="unused", writes="Slide four says 61%.")
    finding = Finding(domain="margin", summary="Slide 4 says 61%; spoken 70%.")

    await interrogate(
        DEFAULT_PANEL, said="Our margin is about 70%.", finding=finding, model=model
    )

    (_, composed_finding), = model.composed_with
    assert composed_finding is finding
