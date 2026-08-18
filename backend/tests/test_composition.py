"""Who ends up in the room, from what somebody said about their meeting.

`docs/onboarding.md`'s central anxiety, stated as a warning rather than a
requirement: *"a reveal backed by a survey that changed nothing is a promise the
first session immediately contradicts — and this audience checks."* These tests
are what make that promise checkable, so the first one is the one the reveal
rests on — the seats hold the people they described.

**Deterministic, and that is the whole design.** The doc's own testing note asks
for *"an assertion on the archetypes selected for a given answer set"*, which is
only writable if no model is consulted. It is the same finding as #43 — asked
*"did the presenter dodge?"* a model said yes on 4 of 4 dodges and 4 of 4
genuine answers — and the same answer: a lookup, not a judgement.
"""

from __future__ import annotations

from app.agents.archetypes import DEFAULT_PANEL
from app.agents.archetypes import by_name
from app.agents.composition import BY_ROLE, SEATING, compose


def test_the_seats_hold_the_people_they_said_would_be_there():
    """The tracer bullet, and the sentence the reveal makes true.

    Order is asserted because the chart is a seating plan: somebody placed a
    person in the first chair, and a room that quietly re-sorts them has
    already stopped being the plan they filled in.
    """
    seated = compose(audience=("budget", "technical"), role=None, seats=2)

    assert [archetype.name for archetype in seated] == ["cfo", "technical_skeptic"]


def test_a_half_filled_plan_is_finished_by_who_the_asker_is():
    """One chip, three chairs — and the other two are not left empty.

    Product.md §2 is why role does this work rather than a generic filler: a
    product manager defending a roadmap and a founder at demo day are not the
    same meeting, and role is the only answer that separates them once the
    chips agree. The placed chairs still come first; a fill is an addition to
    the plan, never a re-sort of it.
    """
    seated = compose(audience=("budget",), role="founder", seats=3)

    assert [archetype.name for archetype in seated] == [
        "cfo",
        "growth_maximalist",
        "technical_skeptic",
    ]


def test_an_empty_plan_still_seats_a_mixed_room():
    """Nothing tapped, no role — and this is the case that matters most.

    `CLAUDE.md`: *"Panel composition should default to mixed, not uniformly
    hostile — ship a champion, a skeptic, and a neutral by default."* That rule
    binds **here**, on the default, and nowhere else. A user who deliberately
    seats three hostile chairs has said what they want, and quietly inserting a
    champion would be the product overruling the plan it just asked them to
    fill in. Open Risk #1 is answered by the difficulty rung (#55), which is a
    dial they can see, not by editing their room behind them.

    Read from `DEFAULT_PANEL` rather than written out, so that changing the
    shipped default moves this assertion with it instead of leaving a lie.
    """
    seated = compose(audience=(), role=None, seats=3)

    assert seated == DEFAULT_PANEL


def test_a_chip_this_build_has_never_heard_of_does_not_take_the_room_down():
    """An app on a different release than the server, at the worst moment.

    This runs at sign-up, at the end of a flow the user has just spent five
    answers on. Refusing the whole plan over one unrecognised key would throw
    away an account rather than a chair — and `auth/schemas.py` already made the
    same call about `provider`, where a closed set was refused because *"a 422
    listing the ones we accept enumerates our configuration"*.

    Dropping is safe here specifically because the reveal renders from the
    server's answer rather than the client's memory. The plan they are shown is
    the room they will get, whatever this build understood.
    """
    seated = compose(audience=("budget", "sommelier"), role=None, seats=3)

    assert [archetype.name for archetype in seated][0] == "cfo"
    assert len(seated) == 3


def test_more_people_than_chairs_fills_the_chairs_there_are():
    """Free seats three, and somebody describes a room of five.

    Truncated rather than refused, on the same reasoning as the unknown chip
    and with the same safety net: the reveal shows what was seated, so nobody
    is told they got a room they did not get. `panel.py` still refuses an
    over-sized panel on the session path, which is the wall that matters —
    this is a plan being read, not a room being minted.
    """
    seated = compose(
        audience=("budget", "technical", "ally", "compliance", "customer"),
        role=None,
        seats=3,
    )

    assert [archetype.name for archetype in seated] == [
        "cfo",
        "technical_skeptic",
        "champion",
    ]


def test_every_seat_this_module_can_name_is_somebody_who_exists():
    """The typo guard, and the reason it is worth its own test.

    `by_name` answers `None` for a name the library does not hold, so a single
    mistyped entry in either table would put a `None` in a seat and fail much
    later, somewhere that has no idea why. `test_panel_limits.py` guards the
    library's own completeness for the same reason; this guards the two tables
    that point at it.
    """
    named = {*SEATING.values(), *(name for fills in BY_ROLE.values() for name in fills)}

    assert all(by_name(name) is not None for name in named)
