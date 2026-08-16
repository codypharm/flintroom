"""A panel taking a turn.

`docs/panel-orchestration.md` settles the shape: pick a speaker, then write that
archetype's line with only their persona in context. What these tests hold is the
part that decides whether four archetypes sound like four people or like one
model wearing four labels.

No model is called. `mocking.md` allows a fake at the vendor boundary, and that is
exactly where this one sits — what is under test is the loop around it.
"""

from __future__ import annotations

from inspect import signature

from app.agents.panel import Asked, Finding, Grounding, interrogate
from app.agents.archetypes import DEFAULT_PANEL, LIBRARY
from app.agents.model import PanelModel
from app.core.errors import ProviderUnavailable


class FakePanelModel:
    """A model that answers what it was told to, and remembers what it was asked."""

    def __init__(
        self,
        *,
        writes: str = "Where does that number come from?",
        selects: str | None = None,
    ) -> None:
        self._writes = writes
        self._selects = selects
        self.asked_to_write_as: list[str] = []
        self.composed_with: list[tuple] = []

    async def select(self, *, candidates, context) -> str:
        # No answer configured means "the model had no opinion", which is the
        # case the fallback exists for rather than an exceptional one.
        if self._selects is None:
            raise ProviderUnavailable(reason="panel_model_error")
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
    model = FakePanelModel(writes="Your margin assumes no churn.")

    turn = await interrogate(
        DEFAULT_PANEL, said="We hold 61% gross margin at scale.", model=model
    )

    assert turn.archetype.name == "cfo"
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
    model = FakePanelModel()

    turn = await interrogate(
        DEFAULT_PANEL, said="We hold 61% gross margin at scale.", model=model
    )

    assert turn.archetype in DEFAULT_PANEL
    assert model.asked_to_write_as == [turn.archetype.name]


async def test_a_finding_is_taken_by_the_archetype_whose_domain_owns_it():
    """§3.3: the CFO catches the margin contradiction, not the Technical Skeptic.

    The finding decides the speaker outright, ahead of ordinary routing.
    `docs/auditor-grounding.md` has each derivation pack declare which archetype
    domain owns a figure, so by the time a finding exists the interrupter is
    already determined — and it must not be re-derived from the words of the
    answer, which may not mention the contested metric at all.

    Getting this wrong is not cosmetic. A panel where the engineer challenges the
    margin reads as a panel that is not listening, which is Open Risk #2 arriving
    by a different route.
    """
    model = FakePanelModel(writes="Margin was 61% on slide four.")

    turn = await interrogate(
        DEFAULT_PANEL,
        said="Our margin is about 70%.",
        finding=Finding(domain="margin", summary="Slide 4 says 61%."),
        model=model,
    )

    assert turn.archetype.name == "cfo"


async def test_the_interrupting_archetype_is_told_what_was_caught():
    """Targeted but ungrounded is the worst of both.

    `CLAUDE.md`: *"do not ship interrogation logic that can't cite its source."*
    An archetype handed the floor because of a contradiction, and then not told
    what the contradiction was, produces a challenge that sounds authoritative
    and cites nothing — which is Open Risk #2 exactly, arriving from the one path
    that was supposed to be the cure for it.
    """
    model = FakePanelModel(writes="Slide four says 61%.")
    finding = Finding(domain="margin", summary="Slide 4 says 61%; spoken 70%.")

    await interrogate(
        DEFAULT_PANEL, said="Our margin is about 70%.", finding=finding, model=model
    )

    (_, composed_finding), = model.composed_with
    assert composed_finding is finding


def test_no_two_archetypes_claim_the_same_domain():
    """Domain ownership decides who interrupts, and `_owner` takes the first match.

    With three archetypes an overlap was unlikely; with a library of eight it is
    one careless entry away, and the failure is silent. A finding tagged `market`
    would go to whoever happens to sit earlier in the tuple — a panel routing by
    declaration order rather than by expertise, which is indistinguishable from a
    panel that is not listening.

    Whoever adds the ninth archetype should be told by a red test, not by a
    transcript that reads oddly six weeks later.
    """
    seen: dict[str, str] = {}
    clashes = []

    for archetype in LIBRARY:
        for domain in archetype.domains:
            if domain in seen:
                clashes.append(f"{domain}: {seen[domain]} and {archetype.name}")
            seen[domain] = archetype.name

    assert clashes == []


def test_the_default_room_is_mixed_rather_than_uniformly_hostile():
    """`CLAUDE.md`: ship a champion, a skeptic and a neutral, and let them disagree.

    Asserted because it is a product decision a later "let's make it harder"
    change would quietly undo. Open Risk #1 is that people may not tolerate being
    attacked at all, and a room with no ally in it is the version of this product
    most likely to be uninstalled after one session.
    """
    assert len(DEFAULT_PANEL) == 3
    assert "champion" in {archetype.name for archetype in DEFAULT_PANEL}


def test_every_archetype_answers_to_the_name_it_is_called_by():
    """`name` is what a model returns and what a log line carries; `title` is what
    the user hears. When they disagree, every transcript and every log needs a
    translation step that exists only in somebody's head.

    This started as `margin_hawk` titled "The CFO" and `customer_voice` titled
    "The Customer Advocate" — harmless until the first support question about why
    a room contains a `margin_hawk` nobody was shown.
    """
    for archetype in LIBRARY:
        expected = archetype.title.removeprefix("The ").lower().replace(" ", "_")
        assert archetype.name == expected, f"{archetype.name} is titled {archetype.title!r}"


async def test_an_archetype_is_given_the_deck_it_is_meant_to_attack():
    """The wedge, in one assertion.

    `CLAUDE.md` refuses to ship interrogation logic that cannot cite its source,
    and Open Risk #2 is that ungrounded generic questions kill retention faster
    than any UI flaw. A composer handed only the last sentence can produce
    nothing better than a hard-sounding question about a subject it has never
    seen — which is the competitor product this one exists to refuse.
    """
    model = FakePanelModel()
    grounding = Grounding(
        claims=("Gross margin of 61% in Q3 2026",),
        asked=(Asked(archetype="cfo", question="What is your CAC payback?"),),
    )

    await interrogate(
        DEFAULT_PANEL, said="Margins are strong.", grounding=grounding, model=model
    )

    (context, _), = model.composed_with
    assert context.grounding is grounding


async def test_a_room_with_no_deck_still_runs():
    """The deckless path is first-class, not degraded (`docs/auditor-grounding.md`).

    A user who does not want to wait for extraction starts without material, and
    §3.2 makes that a supported choice rather than a fallback. The composer gets
    an empty grounding rather than `None`, so nothing downstream has to ask
    whether there is a deck before it can read one — the shape is the same and
    only the contents differ.
    """
    model = FakePanelModel()

    turn = await interrogate(DEFAULT_PANEL, said="We are pre-revenue.", model=model)

    (context, _), = model.composed_with
    assert context.grounding.claims == ()
    assert turn.line


def test_the_fake_the_tests_run_against_is_the_shape_a_vendor_must_fit():
    """A fake that has drifted from the Protocol tests nothing about the real thing.

    Every test in this module drives `FakePanelModel`, so if its signatures stop
    matching `PanelModel` the suite goes on passing while proving progressively
    less — and the first vendor adapter would then be written against a shape
    nothing else agrees with.

    Parameter names rather than `isinstance`, deliberately. A runtime-checkable
    Protocol compares method *names* only, so a fake whose `compose` had quietly
    lost its `finding` argument would still pass — which is exactly the drift
    worth catching, since every call here is keyword-only.
    """
    for method in ("compose",):
        expected = signature(getattr(PanelModel, method)).parameters.keys()
        actual = signature(getattr(FakePanelModel, method)).parameters.keys()
        assert set(expected) == set(actual), method


async def test_a_fast_model_decides_who_speaks():
    """The normal path. Keywords were measured at 53% relevance against realistic
    speech and cannot see a custom archetype at all — a user-authored panelist has
    no entry in any vocabulary table, so it would never be chosen for relevance.

    A model reads the roster as written, including a persona somebody typed this
    morning, and needs nothing maintained.
    """
    model = FakePanelModel(selects="technical_skeptic", writes="Show me the load test.")

    turn = await interrogate(
        DEFAULT_PANEL, said="We're spending more to acquire each customer.", model=model
    )

    assert turn.archetype.name == "technical_skeptic"


async def test_a_model_that_is_late_or_broken_never_silences_the_room():
    """Routing runs while the user is still speaking, so it is usually done before
    it is needed. When it is not — a slow call, a 502, a name nobody answers to —
    the room falls back to keyword routing and somebody speaks immediately.

    A slow model must cost relevance, never silence. This is a live metered room:
    a pause with nobody in it is the failure users notice first, and the one they
    are paying for by the minute.
    """
    class Broken(FakePanelModel):
        async def select(self, *, candidates, context):
            raise ProviderUnavailable(reason="panel_model_error")

    turn = await interrogate(
        DEFAULT_PANEL,
        said="Our gross margin is around seventy percent.",
        model=Broken(writes="Slide four says sixty-one."),
    )

    assert turn.archetype.name == "cfo"
    assert turn.line == "Slide four says sixty-one."
