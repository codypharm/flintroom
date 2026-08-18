"""How hard the room pushes, and what moves it.

`docs/difficulty-calibration.md`. The whole of the design rests on one thing
being true, so it is the first test here: **level 2 is the room that ships
today**. Every figure in `scripts/rotation.py`'s history — the CFO down to 2-4
of 8, three distinct archetypes at every prefix length, 3-4 of 4 dodges pressed
— describes a room with one press and two disputes. If the middle rung is not
that room, none of those measurements describe anything that exists any more,
and the ladder is three guesses rather than one measurement and two steps.
"""

from __future__ import annotations

from app.agents.difficulty import (
    DISPUTES_PER_ROOM,
    GENTLE,
    LADDER,
    RELENTLESS,
    STANDARD,
    pressure_at,
)


def test_the_middle_rung_is_the_room_that_ships_today():
    """The anchor, and the reason there are three rungs rather than four.

    Read from `DISPUTES_PER_ROOM` rather than written as 2, so that changing
    the shipped cap moves the rung with it instead of silently making this
    assertion a lie about history.
    """
    assert pressure_at(STANDARD) == (1, DISPUTES_PER_ROOM)


def test_a_level_nobody_put_on_the_ladder_still_produces_a_room():
    """Clamped, never validated, and the caller is why.

    This is read on the live interrogation path. A row holding 0 or 7 — a bad
    migration, a rung removed later, an operator fat-finger — must produce a
    real room rather than raise, because the alternative is a metered session
    ending over bookkeeping. The panel adapter makes the same call for the same
    reason when a usage field is missing.
    """
    assert pressure_at(-4) == pressure_at(GENTLE)
    assert pressure_at(99) == pressure_at(RELENTLESS)


def test_no_rung_ever_stops_the_room_following_up():
    """The one property the whole ladder is arranged around.

    `_SELECTION_INSTRUCTION`'s docstring records an earlier draft that forbade
    consecutive turns outright, and why it was wrong: *"It gave up the sharpest
    move a room has — the person who asked something noticing it was not
    answered."*

    So the gentle end softens the disputes, never the press. A room that lets
    an unanswered question go by is not a gentler version of this product, it
    is the delivery-coach product the wedge exists to refuse — and it would be
    shipped to the one session that has to sell the difference.

    Asserted across the whole ladder rather than on the floor alone, so that a
    rung added later cannot quietly reintroduce it.
    """
    assert all(rung.presses >= 1 for rung in LADDER)


def test_the_gentle_end_is_the_one_that_stops_panelists_talking_over_you():
    """§434: hostility is the product, humiliation is the churn.

    Being cut across by a colleague is #54's mildly dismissive turn — measured,
    a panelist says "Data ownership is irrelevant without margin" and moves the
    room onto its own question. That is a reasonable thing for a room to do to
    somebody on their fourth session and the wrong thing to do to somebody on
    their first.
    """
    assert pressure_at(GENTLE).disputes == 0
    assert pressure_at(STANDARD).disputes > 0
