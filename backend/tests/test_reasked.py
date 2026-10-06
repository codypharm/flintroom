"""A panelist coming back to the floor must not ask what it already asked.

Reported by a tester on 2026-09-26: the floor moved from the CFO to other
panelists and back, and the CFO came back with the question it had already put.
The composer was told not to — `gemini.py` lists this archetype's earlier
questions under *"do not repeat these"* — and nothing checked whether it
listened. Saturday's room had no deck and an eight-word opening, which is the
case where a persona has least else to say and pulls hardest back to its one
subject.

So the check is code, after the line is written, which is where `CLAUDE.md`
wants anything that must hold: a sentence in a prompt is a request.
"""

from __future__ import annotations

from app.agents.archetypes import DEFAULT_PANEL, by_name
from app.agents.model import ModelReply, TurnUsage
from app.agents.panel import Finding, Grounding, Routed, Said, interrogate
from app.agents.reasked import already_asked
from app.agents.context import USER

CFO = by_name("cfo")

ASKED = "Walk me through how twelve thousand users gets you to profitability."


class ScriptedModel:
    """Writes the lines it is given, in order, and remembers every call."""

    def __init__(self, *lines: str, usage: TurnUsage | None = None) -> None:
        self._lines = list(lines)
        self._usage = usage or TurnUsage()
        self.wrote_as: list[str] = []
        self.contexts: list = []

    async def select(self, *, candidates, context) -> ModelReply:  # pragma: no cover
        raise AssertionError("routed turns never select")

    async def compose(self, *, archetype, context, finding=None, dispute=None, rephrasing=None) -> ModelReply:
        self.wrote_as.append(archetype.name)
        self.contexts.append(context)
        return ModelReply(text=self._lines.pop(0), usage=self._usage)


def _room(*lines: Said) -> Grounding:
    return Grounding(transcript=lines)


#: The CFO asked, the presenter answered, the Skeptic took a turn and was
#: answered. The next CFO line is a *return*, not a press.
RETURNING = _room(
    Said(speaker="cfo", text=ASKED),
    Said(speaker=USER, text="We get there on the enterprise tier."),
    Said(speaker="technical_skeptic", text="What breaks first when load doubles?"),
    Said(speaker=USER, text="The queue, and we shard it by tenant."),
)


# --- the comparison itself ---------------------------------------------------


def test_the_same_question_in_slightly_different_words_is_caught():
    again = "So walk me through how you get from twelve thousand users to profitability."

    assert already_asked(again, [ASKED]) == ASKED


def test_a_short_question_asked_word_for_word_is_caught():
    """Too few words for an overlap score to mean anything, and still a repeat."""
    assert already_asked("What's your margin?", ["What's your margin?"]) == "What's your margin?"


def test_a_new_question_on_the_same_subject_is_not_a_repeat():
    """The CFO exists to press margin. Two margin questions are not one question.

    The failure on this side is the one `context.py` already warns about: a
    panelist steered off the subject it exists to press is worse than one that
    repeats itself.
    """
    earlier = ["What is your gross margin once you pay for onboarding?"]

    assert already_asked("How does gross margin hold when you double headcount?", earlier) is None


def test_nothing_asked_yet_is_never_a_repeat():
    assert already_asked(ASKED, []) is None


# --- the room ----------------------------------------------------------------


async def test_a_returning_panelist_that_repeats_itself_is_sent_back_once():
    model = ScriptedModel(
        "Walk me through how you get from twelve thousand users to profitability.",
        "What does one enterprise customer cost you to land?",
    )

    turn = await interrogate(
        DEFAULT_PANEL,
        said="And the pilot converts next month.",
        model=model,
        grounding=RETURNING,
        routed=Routed(CFO, "model"),
    )

    assert turn.archetype.name == "cfo"
    assert turn.line == "What does one enterprise customer cost you to land?"
    # The rewrite is told what it was about to repeat, not just told again not to.
    assert model.contexts[0].repeated == ""
    assert model.contexts[1].repeated == ASKED


async def test_a_panelist_that_repeats_itself_twice_gives_up_the_floor():
    model = ScriptedModel(
        "Walk me through how you get from twelve thousand users to profitability.",
        "Walk me through how twelve thousand users get you to profitability, then.",
        "Who signs off on the enterprise contract?",
    )

    turn = await interrogate(
        DEFAULT_PANEL,
        said="And the pilot converts next month.",
        model=model,
        grounding=RETURNING,
        routed=Routed(CFO, "model"),
    )

    assert turn.archetype.name != "cfo"
    assert model.wrote_as[:2] == ["cfo", "cfo"]
    assert model.wrote_as[2] == turn.archetype.name
    assert turn.line == "Who signs off on the enterprise contract?"
    # Code took the floor off the model's pick, which is what `fallback` means.
    assert turn.chosen_by == "fallback"


async def test_a_press_straight_after_its_own_question_is_left_alone():
    """Pressing an unanswered question is the room working, not repeating."""
    pressing = _room(
        Said(speaker="cfo", text=ASKED),
        Said(speaker=USER, text="We are confident in the model."),
    )
    model = ScriptedModel(ASKED)

    turn = await interrogate(
        DEFAULT_PANEL,
        said="We are confident in the model.",
        model=model,
        grounding=pressing,
        routed=Routed(CFO, "model"),
    )

    assert turn.line == ASKED
    assert model.wrote_as == ["cfo"]


#: The CFO kept the floor for two questions running. Reported 2026-10-06: a
#: panelist asked, asked something else, then asked the first one again. Every
#: one of those turns was "a press", so nothing was ever checked.
HOLDING = _room(
    Said(speaker="cfo", text=ASKED),
    Said(speaker=USER, text="We get there on the enterprise tier."),
    Said(speaker="cfo", text="What does one enterprise customer cost you to land?"),
    Said(speaker=USER, text="About forty thousand, all in."),
)


async def test_a_panelist_holding_the_floor_cannot_go_back_to_an_older_question():
    model = ScriptedModel(
        "So walk me through how you get from twelve thousand users to profitability.",
        "How long before that forty thousand comes back to you?",
    )

    turn = await interrogate(
        DEFAULT_PANEL,
        said="About forty thousand, all in.",
        model=model,
        grounding=HOLDING,
        routed=Routed(CFO, "model"),
    )

    assert turn.archetype.name == "cfo"
    assert turn.line == "How long before that forty thousand comes back to you?"
    assert model.contexts[1].repeated == ASKED


async def test_a_press_may_still_put_the_question_it_just_asked():
    """Only the newest question is open to a press; the dial exists for it."""
    last = "What does one enterprise customer cost you to land?"
    model = ScriptedModel(last)

    turn = await interrogate(
        DEFAULT_PANEL,
        said="About forty thousand, all in.",
        model=model,
        grounding=HOLDING,
        routed=Routed(CFO, "model"),
    )

    assert turn.line == last
    assert model.wrote_as == ["cfo"]


async def test_an_auditor_catch_is_never_rewritten_or_handed_away():
    """§3.3: the owner of the domain puts the contradiction. Nobody else can."""
    model = ScriptedModel(ASKED)

    turn = await interrogate(
        DEFAULT_PANEL,
        said="Twelve thousand users gets us there.",
        model=model,
        grounding=RETURNING,
        finding=Finding(domain="margin", summary="Said 61% margin, then 70%."),
    )

    assert turn.archetype.name == "cfo"
    assert model.wrote_as == ["cfo"]


async def test_every_line_written_is_paid_for():
    """A rejected draft still cost what the provider charged for it."""
    model = ScriptedModel(
        "Walk me through how you get from twelve thousand users to profitability.",
        "What does one enterprise customer cost you to land?",
        usage=TurnUsage(input_tokens=100, output_tokens=10),
    )

    turn = await interrogate(
        DEFAULT_PANEL,
        said="And the pilot converts next month.",
        model=model,
        grounding=RETURNING,
        routed=Routed(CFO, "model"),
    )

    assert turn.usage == TurnUsage(input_tokens=200, output_tokens=20)
