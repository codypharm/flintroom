"""What the room says when nobody has said anything for a while.

#24, and the fifth of the five things that look like silence. The other four are
now told apart — three by `Attending` and one by the debrief's refusals — and
this is the one where the room is about to end and take the session with it.

**Spoken rather than shown**, decided by the architect and argued for in #24
before that: the phone is face-up on a desk and a visual warning "arrives at the
moment attention is lowest, aimed at someone who has by definition stopped
looking". Somebody who stepped away to find a figure is exactly who this is
for, and they cannot see the screen. Only sound reaches them.
"""

from __future__ import annotations

from app.agents.archetypes import DEFAULT_PANEL, LIBRARY
from app.agents.silence import NUDGE_AFTER_SECS, Silence, nudge_from
from app.modules.sessions.schemas import IDLE_LIMIT


def test_the_room_asks_before_it_gives_up_on_them():
    """Sixty seconds, with the room ending at ninety.

    Chosen against a real tension. `IDLE_LIMIT`'s own docstring says ninety
    seconds is "long enough to sit through a hostile question and think before
    answering" — so warning too early nags somebody doing exactly what the room
    asked of them. Warning too late leaves no time to answer.
    """
    assert NUDGE_AFTER_SECS < IDLE_LIMIT.total_seconds()

    # Enough left to say something and keep the room. The meter sweeps every
    # fifteen seconds, so the reap actually lands between ninety and a hundred
    # and five — this has to be usable inside the pessimistic end of that.
    assert IDLE_LIMIT.total_seconds() - NUDGE_AFTER_SECS >= 25


def test_nothing_is_said_while_they_are_still_within_their_thinking():
    silence = Silence()

    assert not silence.worth_asking(quiet_for=NUDGE_AFTER_SECS - 1)


def test_the_room_asks_once_the_quiet_has_gone_on_long_enough():
    silence = Silence()

    assert silence.worth_asking(quiet_for=NUDGE_AFTER_SECS)


def test_the_room_asks_once_and_then_lets_it_go():
    """A room that asks twice has stopped being a room and become a smoke alarm."""
    silence = Silence()

    silence.asked()

    assert not silence.worth_asking(quiet_for=NUDGE_AFTER_SECS * 5)


def test_speaking_again_earns_another_one_later_in_the_room():
    """Once per stretch of silence, not once per session.

    Somebody who steps away, comes back, answers three questions and steps away
    again has been present the whole time in between. Refusing to ask a second
    time would make the feature useless for exactly the person it is for.
    """
    silence = Silence()
    silence.asked()

    silence.heard()

    assert silence.worth_asking(quiet_for=NUDGE_AFTER_SECS)


def test_every_shipped_archetype_can_ask():
    for archetype in LIBRARY:
        assert archetype.nudges, f"{archetype.name} cannot ask if anybody is there"


def test_nobody_asks_in_words_a_model_wrote():
    """Hand-written, like the openers, and for a sharper reason.

    This is spoken to somebody who may have walked away from a room that is
    billing them by the minute. It has to be short, unmistakable, and the same
    every time it is heard — and a composed line is none of those, on top of
    being a model call made about nothing at all.
    """
    for archetype in LIBRARY:
        for line in archetype.nudges:
            assert len(line.split()) <= 10, f"{archetype.name}: {line!r}"
            assert "[" not in line and "]" not in line


def test_two_archetypes_never_ask_the_same_way():
    seen: dict[str, str] = {}

    for archetype in LIBRARY:
        for line in archetype.nudges:
            assert line not in seen, f"{archetype.name} and {seen[line]} share {line!r}"
            seen[line] = archetype.name


def test_it_is_asked_by_somebody_at_the_table():
    who, line = nudge_from(DEFAULT_PANEL, choose=lambda options: options[0])

    assert who is DEFAULT_PANEL[0]
    assert line in DEFAULT_PANEL[0].nudges
