"""The stretch at the start of a room where nobody interrupts.

#79. Measured on a live room (066f32db, 2026-08-19): the panel composed its
first challenge against an empty transcript and invented the subject — a
"pipeline" the presenter never mentioned — then attacked its own invention for
six more turns. `_listen` acted on the first transcriber final, and finals
commit after 0.7s of silence, which is shorter than the pause inside anybody's
opening sentence.

This is the state machine that decides when the floor stops being the
presenter's. Pure and clock-injected, because everything interesting about it is
arithmetic on words and seconds, and none of it should need a socket to test.
"""

from __future__ import annotations

from app.agents.opening import (
    HARD_CAP,
    SETTLE_PAUSE,
    SUBSTANCE_WORDS,
    OpeningFloor,
)


def test_a_new_room_belongs_to_the_presenter():
    floor = OpeningFloor()

    assert floor.open
    assert floor.words == 0


def test_words_accumulate_across_the_pauses_inside_a_sentence():
    """An opening statement arrives as several finals, not one.

    The transcriber commits after 0.7s, so a person drawing breath produces two
    finals for one thought. Counting per-final would judge each fragment against
    the substance floor and find every one of them thin.
    """
    floor = OpeningFloor()

    floor.heard("We run a logistics business")
    floor.heard("and we have been profitable for two years")

    assert floor.words == 13


def test_an_opening_below_the_substance_floor_is_thin():
    floor = OpeningFloor(substance=10)

    floor.heard("Hi. So, yeah.")

    assert floor.thin


def test_an_opening_that_reaches_the_floor_is_not_thin():
    floor = OpeningFloor(substance=5)

    floor.heard("We move freight for mid-market retailers")

    assert not floor.thin


def test_the_room_waits_a_settle_pause_after_each_thing_they_say():
    """Longer than the transcriber's own 0.7s, or the pause inside a sentence
    reads as the end of the statement — which is the bug this exists to fix."""
    floor = OpeningFloor(settle=2.5, cap=90.0)

    assert floor.wait_for(elapsed=3.0) == 2.5
    assert SETTLE_PAUSE > 0.7


def test_the_settle_pause_clears_a_section_break_breath():
    """A rhetorical pause is not a handover.

    Observed on the first Play build (Kettleworks run, 2026-08-26): a presenter
    reading a prepared ninety-second opening was closed on mid-statement at a
    section break, and the questioning began with the case half made. A pause
    between sections of a rehearsed opening runs about three seconds, so the
    settle has to clear it with room to spare -- while staying a wait a person
    who has genuinely finished will sit through.
    """
    assert SETTLE_PAUSE >= 4.0


def test_the_wait_never_reaches_past_the_cap():
    """Somebody who talks without stopping still gets interrogated.

    Without this a twelve-minute monologue is a rehearsal nobody attended, and
    the room the user paid for never happened.
    """
    floor = OpeningFloor(settle=2.5, cap=90.0)

    assert floor.wait_for(elapsed=89.0) == 1.0
    assert floor.wait_for(elapsed=90.0) == 0.0
    assert floor.wait_for(elapsed=200.0) == 0.0


def test_closing_hands_back_the_whole_opening_as_one_utterance():
    """The turn is composed against everything they said, not the last fragment.

    `_answer` takes one `said` string, and handing it only the final fragment
    would ground the room's first challenge in the tail of a sentence.
    """
    floor = OpeningFloor()

    floor.heard("We move freight for mid-market retailers.")
    floor.heard("Margin is thirty per cent.")

    opening = floor.close()

    assert opening.text == (
        "We move freight for mid-market retailers. Margin is thirty per cent."
    )
    assert not floor.open


def test_a_closed_floor_stays_closed():
    """The settle timer and the cap can both fire. Only one may open a turn."""
    floor = OpeningFloor()
    floor.heard("Something.")

    floor.close()

    assert not floor.open


def test_an_opening_nobody_gave_closes_thin_rather_than_empty():
    """The presenter said nothing at all before the cap.

    Distinct from the empty-final case (#77) — there is genuinely nothing here,
    and the room owes them a question rather than a challenge to no statement.
    """
    floor = OpeningFloor()

    opening = floor.close()

    assert opening.text == ""
    assert opening.thin


def test_the_shipped_numbers_are_the_ones_the_room_uses():
    """Defaults, so a room built without arguments is the room that ships.

    The same property `STANDARD_PRESSURE` holds for difficulty: one object
    rather than two lists that can disagree about what shipped.
    """
    floor = OpeningFloor()

    assert floor.wait_for(elapsed=0.0) == SETTLE_PAUSE
    assert floor.wait_for(elapsed=HARD_CAP) == 0.0

    floor.heard(" ".join(["word"] * SUBSTANCE_WORDS))
    assert not floor.thin
