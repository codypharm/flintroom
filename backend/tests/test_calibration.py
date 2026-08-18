"""Moving the rung between rooms.

`docs/difficulty-calibration.md` decision 2. Separate from `test_difficulty.py`
because the modules are separate, and they are separate because the ladder has
no dependencies and this needs the weakness vocabulary — which is what lets
`TurnContext` carry a `Pressure` without a cycle.

What is under test here is a policy, not arithmetic: which weaknesses count,
how far one room may move somebody, and which rooms are not evidence at all.
"""

from __future__ import annotations

from app.agents.calibration import calibrate
from app.agents.difficulty import GENTLE, RELENTLESS, STANDARD
from app.agents.weakness import WeakAnswer, Weakness


def room(*kinds: Weakness) -> tuple[WeakAnswer, ...]:
    """Weak answers of the given kinds, with the rest of the shape filled in.

    Nothing here reads the quote or the ordinal — calibration counts kinds —
    but they are real values rather than blanks, because `WeakAnswer` is the
    type that survived `verified()` and a test that built an impossible one
    would be describing a row the debrief cannot produce.
    """
    return tuple(
        WeakAnswer(
            ordinal=index,
            question="Off what base, and at what cost?",
            asked_by="cfo",
            answer="We are really pleased with the trajectory.",
            weakness=kind,
            why="You answered with a feeling about the trend, not a base.",
        )
        for index, kind in enumerate(kinds)
    )


def test_a_room_they_mostly_fumbled_makes_the_next_one_gentler():
    """Open Risk #1, in one function.

    Four questions and two of them evaded is a session that went badly enough
    that pressing harder next time produces churn rather than resilience. The
    whole feature exists for this direction; escalation is the easy half.
    """
    fumbled = room(Weakness.EVASIVE, Weakness.UNSUPPORTED)

    assert calibrate(RELENTLESS, weak=fumbled, questions=4) == STANDARD


def test_what_the_room_did_to_them_is_not_counted_against_them():
    """#56, defended in arithmetic instead of only in layout.

    Four questions, two of them gone — one because a colleague cut across the
    presenter, one because the clock ran out. Neither is evidence about the
    person, and `PrepSheet.tsx` already tells them so under "Not on you".

    Counting them would make the product say one thing on the prep sheet and do
    the opposite to the next room: told it was not their fault, and handed a
    gentler session as though it had been. This is the single most load-bearing
    assertion in the file.
    """
    not_their_doing = room(Weakness.DISMISSED, Weakness.NOT_REACHED)

    assert calibrate(RELENTLESS, weak=not_their_doing, questions=4) == RELENTLESS


def test_a_room_they_handled_raises_the_next_one():
    """The escalation the spec actually asks for.

    Five questions and one fumbled is a fifth, which is the handled threshold.
    `Product.md` §434 wants intensity to escalate across sessions; this is the
    only place it does.
    """
    handled = room(Weakness.EVASIVE)

    assert calibrate(GENTLE, weak=handled, questions=5) == STANDARD


def test_a_flawless_room_still_only_moves_one_rung():
    """The guard on the model in the loop.

    The reading behind these is a model's, decided in #57 because code cannot
    see a fluent, specific, confidently wrong answer. A model in a feedback
    loop can run away, so a reader having a bad week costs a user one rung and
    never the whole ladder.
    """
    assert calibrate(GENTLE, weak=(), questions=6) == STANDARD


def test_the_ladder_has_ends():
    """Nobody climbs off the top or falls through the floor."""
    assert calibrate(RELENTLESS, weak=(), questions=6) == RELENTLESS
    assert calibrate(GENTLE, weak=room(Weakness.EVASIVE) * 3, questions=4) == GENTLE


def test_a_room_that_asked_nothing_moves_nothing():
    """No questions, no proportion, no signal.

    Not a hypothetical: `DebriefService.weak_answers` refuses a room with no
    questions outright, and this agrees with that refusal rather than inventing
    an answer of its own. A division here would be a crash on the settle path.
    """
    assert calibrate(STANDARD, weak=(), questions=0) == STANDARD
