"""What the room says when its time is up, before the meter takes it.

The architect's room ended at 12:12 mid-sentence — the session cap doing its
documented job, experienced as a malfunction, because the room never said
anything. A meeting ends; a call drops. The difference is one spoken line.

**After whoever is speaking, never over them.** The architect's second
constraint, and the same discipline the silence nudge already holds: the
orchestrator only says this on a beat where no panelist is mid-line and the
presenter has paused. The meter still owns the money and the actual close —
this line changes what the ending feels like, not when it lands or what it
costs.
"""

from __future__ import annotations

from app.agents.archetypes import DEFAULT_PANEL, LIBRARY
from app.agents.closing import CALL_BEFORE_SECS, TimeCall, closer_from
from app.modules.sessions.schemas import SESSION_LIMIT

CAP = SESSION_LIMIT.total_seconds()


def test_the_call_lands_inside_the_room_it_is_about():
    """Early enough to say and hear a last word, late enough to be true.

    The meter sweeps every fifteen seconds and reaps between 12:00 and 12:15,
    so anything under ~15 seconds of margin risks the line being cut off by
    the very ending it announces, and a minute-plus would announce an ending
    that is not near.
    """
    assert 15 <= CALL_BEFORE_SECS <= 60


def test_nothing_is_said_while_the_room_still_has_time():
    call = TimeCall()

    assert not call.worth_calling(elapsed=CAP - CALL_BEFORE_SECS - 1)


def test_the_room_calls_time_once_the_end_is_near():
    call = TimeCall()

    assert call.worth_calling(elapsed=CAP - CALL_BEFORE_SECS)


def test_time_is_called_once_and_only_once():
    """A room that keeps announcing the end is a boarding gate, not a panel."""
    call = TimeCall()
    assert call.worth_calling(elapsed=CAP - 5)
    call.called()

    assert not call.worth_calling(elapsed=CAP - 1)
    assert not call.worth_calling(elapsed=CAP + 60)


def test_every_shipped_archetype_can_call_time():
    """The guarantee every hand-written line set relies on:
    `docs/custom-archetypes.md` seats at least one shipped archetype in every
    room precisely because openers, nudges and this are written by hand, and a
    row a user typed carries none of them."""
    for archetype in LIBRARY:
        assert archetype.closers, f"{archetype.name} cannot call time"


def test_no_two_archetypes_call_time_the_same_way():
    lines: list[str] = []
    for archetype in LIBRARY:
        lines.extend(archetype.closers)

    assert len(lines) == len(set(lines))


def test_time_is_called_by_somebody_at_the_table():
    who, line = closer_from(DEFAULT_PANEL, choose=lambda options: options[0])

    assert who in DEFAULT_PANEL
    assert line in who.closers


def test_the_line_never_carries_a_verdict():
    """The scale language rule, held here too: the room may end, it may ask
    for a last word, and it may not grade. "That's time" is a chair speaking;
    "you did well" is a scorecard."""
    for archetype in LIBRARY:
        for line in archetype.closers:
            said = line.lower()
            for verdict in ("well done", "good job", "you did", "score", "passed", "failed"):
                assert verdict not in said, f"{archetype.name} grades on the way out"
