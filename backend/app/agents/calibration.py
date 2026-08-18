"""Where the next room sits, given how this one went.

`docs/difficulty-calibration.md`. Separate from `difficulty.py` because the doc
separates them — *"the stored fact is the difficulty level; the process that
moves it is calibration"* — and because the dependency shapes differ: the ladder
is a value object with no imports, and this needs the weakness vocabulary.

That split is what lets `context.TurnContext` carry a `Pressure` at all.
`weakness` imports `context`, so a ladder that also counted weak answers could
never be imported by the thing it describes.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.agents.difficulty import GENTLE, LADDER
from app.agents.weakness import PRESENTER_AT_FAULT, WeakAnswer

#: A room this badly handled lowers the rung: half its questions or worse.
#:
#: **A judgement with no data behind it**, in exactly the position every price
#: in `Product.md` §4.4 occupied before §4.3 was built. It should be revisited
#: against real rooms, and `docs/difficulty-calibration.md` is the thing to edit
#: when it is.
FUMBLED = 0.5

#: A room this well handled raises it: a fifth of its questions or better.
HANDLED = 0.2


def calibrate(level: int, *, weak: Sequence[WeakAnswer], questions: int) -> int:
    """The rung the next room should be on.

    **One rung, either way, never more.** The reading behind `weak` comes from
    a model — #57 decided that deliberately, because code cannot see a fluent,
    specific, confidently wrong answer — and a model in a feedback loop is a
    model that can run away. A reader having a bad week costs a user one rung
    and not four.

    **Only what the presenter was at fault for counts.** `dismissed` and
    `not_reached` are the room's doing, and letting them push somebody down
    would undo #56 through arithmetic instead of through layout: told on the
    prep sheet that it was not their fault, and handed a gentler room as though
    it had been.

    A room with no questions in it does not move anything. There is no
    proportion to take, and the case is real — `DebriefService.weak_answers`
    already refuses such a room outright, so this agrees with that refusal
    rather than inventing an answer of its own.

    Takes whole `WeakAnswer`s rather than a count so that the fault split
    happens in here. A signature taking `faults: int` would put #56 in every
    caller, where it can be forgotten once and be wrong forever.
    """
    if questions <= 0:
        return _rung(level)

    faults = sum(1 for answer in weak if answer.weakness in PRESENTER_AT_FAULT)
    share = faults / questions

    if share >= FUMBLED:
        return _rung(level - 1)
    if share <= HANDLED:
        return _rung(level + 1)
    return _rung(level)


def _rung(level: int) -> int:
    """A level that is actually on the ladder.

    Clamped here as well as in `pressure_at`, and the duplication is
    deliberate: this one keeps the *stored* number sane, and that one keeps the
    *live room* running whatever is stored. Collapsing them would mean either
    writing 4 into a column or raising inside a metered session.
    """
    return min(max(level, GENTLE), len(LADDER))
