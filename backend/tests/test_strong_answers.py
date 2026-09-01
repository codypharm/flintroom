"""What held in the room, read back off the same transcript — #118.

The debrief has only ever reported failure: six categories, all of them
faults, and a presenter who did well was shown a shorter list of what they
did badly. Testers asked for a rating. The product's answer is a score
counted in code from verified findings — and counting what held requires
finding what held, which nothing did before this.

The discipline is the one `verified` already enforces on weaknesses, for the
opposite temptation: a model told to find strengths will flatter, and a
strength must quote the line it praises or be dropped. A model that wants to
be encouraging cannot invent a good answer nobody gave.
"""

from __future__ import annotations

from app.agents.context import USER, Said
import pytest

from app.agents.weakness import (
    Judgement,
    Strength,
    StrengthJudgement,
    StrongAnswer,
    WeakAnswer,
    Weakness,
    WeaknessReading,
    score,
    verified_strengths,
    weak_answers,
)
from app.modules.sessions.schemas import EndReason



ROOM = (
    Said(speaker=USER, text="We grew forty percent last quarter."),
    Said(speaker="The CFO", text="Forty percent from what base?"),
    Said(speaker=USER, text="From two million ARR, so we ended at two point eight."),
)


def test_a_strength_that_quotes_the_room_survives_with_the_answer_attached():
    judged = (
        StrengthJudgement(
            ordinal=1,
            quote="Forty percent from what base?",
            strength=Strength.HELD,
            why="You had the base ready and the arithmetic held.",
        ),
    )

    (strong,) = verified_strengths(judged, ROOM)

    assert strong.question == "Forty percent from what base?"
    assert strong.asked_by == "The CFO"
    assert strong.answer == "From two million ARR, so we ended at two point eight."
    assert strong.strength is Strength.HELD
    assert strong.why == "You had the base ready and the arithmetic held."


def test_a_strength_that_quotes_something_nobody_said_is_dropped():
    judged = (
        StrengthJudgement(
            ordinal=1,
            quote="What is your churn rate?",
            strength=Strength.DIRECT,
            why="A clean, direct answer.",
        ),
    )

    assert verified_strengths(judged, ROOM) == ()


def test_a_strength_on_a_question_nobody_answered_is_dropped():
    """An answer that held must exist. Praising silence is the flattery the
    quote check alone cannot catch — the quote is real, the question was
    asked, and nothing came back."""
    unanswered = ROOM[:2]

    judged = (
        StrengthJudgement(
            ordinal=1,
            quote="Forty percent from what base?",
            strength=Strength.HELD,
            why="You had the base ready.",
        ),
    )

    assert verified_strengths(judged, unanswered) == ()


def test_the_score_counts_held_over_held_plus_faults():
    strong = (
        StrongAnswer(
            ordinal=1,
            question="Forty percent from what base?",
            asked_by="The CFO",
            answer="From two million ARR.",
            strength=Strength.HELD,
            why="The base was ready.",
        ),
    ) * 2

    weak = (
        WeakAnswer(
            ordinal=3,
            question="What is churn?",
            asked_by="The CFO",
            answer="We focus on growth.",
            weakness=Weakness.EVASIVE,
            why="Not the question.",
        ),
    )

    assert score(strong, weak) == (2, 3)


def test_what_the_room_took_away_never_reaches_the_denominator():
    """A colleague cutting across them, or the clock — neither is evidence
    about the presenter, and neither may cost them a point. #56's fault
    split, applied to arithmetic instead of layout."""
    strong = (
        StrongAnswer(
            ordinal=1,
            question="Forty percent from what base?",
            asked_by="The CFO",
            answer="From two million ARR.",
            strength=Strength.GROUNDED,
            why="A source, not an assertion.",
        ),
    )

    weak = (
        WeakAnswer(
            ordinal=3,
            question="What about data ownership?",
            asked_by="The Skeptic",
            answer=None,
            weakness=Weakness.DISMISSED,
            why="A colleague moved the room on.",
        ),
        WeakAnswer(
            ordinal=5,
            question="Walk me through the margin.",
            asked_by="The CFO",
            answer=None,
            weakness=Weakness.NOT_REACHED,
            why="The clock took it.",
        ),
    )

    assert score(strong, weak) == (1, 1)


class ReaderWithBothHalves:
    """A reader that praises one answer and faults another."""

    async def rank(self, *, room):
        return WeaknessReading(
            judged=(
                Judgement(
                    ordinal=3,
                    quote="What is your churn rate?",
                    weakness=Weakness.EVASIVE,
                    why="You answered about growth instead.",
                ),
            ),
            strong=(
                StrengthJudgement(
                    ordinal=1,
                    quote="Forty percent from what base?",
                    strength=Strength.HELD,
                    why="The base was ready and the arithmetic held.",
                ),
            ),
        )


async def test_one_reading_returns_both_halves_each_verified():
    room = ROOM + (
        Said(speaker="The Skeptic", text="What is your churn rate?"),
        Said(speaker=USER, text="Growth is the story this quarter."),
    )

    ranked = await weak_answers(
        room, ended=EndReason.USER_ENDED, reader=ReaderWithBothHalves()
    )

    (weak,) = ranked.answers
    (strong,) = ranked.strong
    assert weak.weakness is Weakness.EVASIVE
    assert strong.strength is Strength.HELD
    assert strong.answer == "From two million ARR, so we ended at two point eight."


def test_the_reported_held_list_becomes_typed_strengths_in_order():
    from app.agents.weakness import to_strengths

    reported = {
        "held": [
            {
                "ordinal": 1,
                "quote": "Forty percent from what base?",
                "strength": "held",
                "why": "The base was ready.",
            },
            {
                "ordinal": 3,
                "quote": "Walk me through the margin.",
                "strength": "grounded",
                "why": "You named the source.",
            },
        ]
    }

    first, second = to_strengths(reported)
    assert first.strength is Strength.HELD
    assert second.strength is Strength.GROUNDED


def test_a_malformed_or_invented_category_costs_the_item_not_the_list():
    from app.agents.weakness import to_strengths

    reported = {
        "held": [
            {"ordinal": "one", "quote": "q", "strength": "held", "why": "w"},
            {"ordinal": 1, "quote": "q", "strength": "brilliant", "why": "w"},
            "not even a dict",
            {
                "ordinal": 1,
                "quote": "Forty percent from what base?",
                "strength": "direct",
                "why": "You answered the thing asked.",
            },
        ]
    }

    (kept,) = to_strengths(reported)
    assert kept.strength is Strength.DIRECT


def test_a_reply_with_no_held_list_is_an_empty_answer_not_an_error():
    from app.agents.weakness import to_strengths

    assert to_strengths({}) == ()
    assert to_strengths({"held": "yes"}) == ()
    assert to_strengths(None) == ()


def test_a_question_praised_twice_counts_once():
    """The score counts questions, not labels. A model that files the same
    answer as held AND grounded has read one answer, and the first filing
    wins because order is the model's."""
    judged = (
        StrengthJudgement(
            ordinal=1,
            quote="Forty percent from what base?",
            strength=Strength.HELD,
            why="The figure survived.",
        ),
        StrengthJudgement(
            ordinal=1,
            quote="Forty percent from what base?",
            strength=Strength.GROUNDED,
            why="You named the source.",
        ),
    )

    (kept,) = verified_strengths(judged, ROOM)
    assert kept.strength is Strength.HELD


async def test_a_question_in_both_lists_is_a_fault_not_a_strength():
    """A reading that praises and faults the same answer has contradicted
    itself. The weakness wins — the product's premise is the grill, and a
    presenter told an answer held will give it again to a real room."""

    class ContradictoryReader:
        async def rank(self, *, room):
            return WeaknessReading(
                judged=(
                    Judgement(
                        ordinal=1,
                        quote="Forty percent from what base?",
                        weakness=Weakness.UNSUPPORTED,
                        why="Two point eight was asserted with nothing behind it.",
                    ),
                ),
                strong=(
                    StrengthJudgement(
                        ordinal=1,
                        quote="Forty percent from what base?",
                        strength=Strength.HELD,
                        why="The base was ready.",
                    ),
                ),
            )

    ranked = await weak_answers(
        ROOM, ended=EndReason.USER_ENDED, reader=ContradictoryReader()
    )

    assert len(ranked.answers) == 1
    assert ranked.strong == ()
