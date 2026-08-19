"""The first thing anybody hears, and the one line no model writes.

#79, decision 6. The opener is spoken at the exact moment the room holds nothing
— no transcript, and possibly no material — so asking a model to compose it is
asking it to do the precise thing the opening floor exists to prevent. A
hand-written line cannot hallucinate, costs no model call, and stays out of the
latency budget entirely.

Per archetype rather than shared, because `Product.md` §3.3 names the failure
this product dies of as *synthetic within two minutes* — one voice wearing four
costumes — and a shared opener is exactly that, at the single moment of first
impression.
"""

from __future__ import annotations

from app.agents.archetypes import LIBRARY
from app.agents.opening import opener_from


def test_every_shipped_archetype_can_open_a_room():
    """Any of them may be drawn, so any of them must have something to say."""
    for archetype in LIBRARY:
        assert archetype.openers, f"{archetype.name} cannot open a room"


def test_nobody_opens_the_same_way_twice_running():
    """One line each would ship a per-archetype list and play it like a constant."""
    for archetype in LIBRARY:
        assert len(archetype.openers) >= 2, f"{archetype.name} has only one opener"


def test_an_opener_is_short_enough_to_be_a_handoff():
    """It hands over the floor; it is not a speech.

    The composer is held to 25 words for a *challenge*, and this is doing far
    less work than a challenge.
    """
    for archetype in LIBRARY:
        for line in archetype.openers:
            assert len(line.split()) <= 15, f"{archetype.name}: {line!r}"


def test_no_opener_carries_a_bracket():
    """`_spoken` strips them before synthesis, so a bracket is a deleted word.

    The same guard `_persona_of` warns the composer about, applied to copy we
    write ourselves — where it is cheaper to enforce than to remember.
    """
    for archetype in LIBRARY:
        for line in archetype.openers:
            assert "[" not in line and "]" not in line, f"{archetype.name}: {line!r}"


def test_two_archetypes_never_share_a_line():
    """The property the per-archetype decision was made for.

    Twenty-four lines that overlap would be a shared list with extra steps.
    """
    seen: dict[str, str] = {}

    for archetype in LIBRARY:
        for line in archetype.openers:
            assert line not in seen, f"{archetype.name} and {seen[line]} share {line!r}"
            seen[line] = archetype.name


def test_the_room_is_opened_by_somebody_at_the_table():
    """Drawn from the seated panel, never from the library.

    A voice belonging to somebody who is not in the room is a narrator, and this
    product deliberately has none.
    """
    seated = LIBRARY[:3]

    who, line = opener_from(seated, choose=lambda options: options[0])

    assert who is seated[0]
    assert line in seated[0].openers


def test_the_same_draw_produces_the_same_room_twice():
    """Injected rather than calling `random` inline.

    `scripts/rotation.py` measures selection across a run, and a room that
    cannot be repeated cannot be measured. The same reason `difficulty.py` is
    integers rather than an adjective in a prompt.
    """
    seated = LIBRARY[:3]

    first = opener_from(seated, choose=lambda options: options[-1])
    again = opener_from(seated, choose=lambda options: options[-1])

    assert first == again


def test_the_speaker_and_the_line_come_from_the_same_draw():
    """Or the CFO opens in the Champion's words."""
    seated = LIBRARY[:3]

    who, line = opener_from(seated, choose=lambda options: options[1])

    assert line in who.openers
