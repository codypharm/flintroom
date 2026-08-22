"""The room calling time on itself, out loud.

The session cap (`SESSION_LIMIT`) is enforced by the meter and experienced,
until this, as the line going dead mid-sentence — the architect's own room
ended at 12:12 that way and read as a malfunction. A meeting ends; a call
drops. What separates the two is somebody in the room saying so.

The shape is the silence nudge's, deliberately: hand-written lines on the
shipped archetypes (a composed line would be a model call about nothing),
spoken only when the floor is free, and changing nothing about the money —
the meter still closes and settles the room exactly as before. This module
owns *when it is worth saying* and *who says it*; the orchestrator owns the
floor discipline, as it does for the nudge.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from app.agents.archetypes import Archetype
from app.agents.opening import Chooser, NoOneToOpen
from app.modules.sessions.schemas import SESSION_LIMIT

#: How long before the cap the room calls time. The meter sweeps every
#: fifteen seconds and reaps between the cap and one sweep past it, so under
#: ~15 the line risks being cut off by the ending it announces; a minute-plus
#: announces an ending that is not yet near. Thirty leaves room to say it and
#: to hear a short last word.
CALL_BEFORE_SECS = 30.0


class TimeCall:
    """Whether the end is near enough to say so, asked once per room.

    The same once-only shape as `Silence`, without the reset: a presenter who
    speaks again has not bought the room more time, so there is nothing that
    could earn a second call. A room that keeps announcing its end is a
    boarding gate, not a panel.
    """

    def __init__(self) -> None:
        self._called = False

    def worth_calling(self, *, elapsed: float) -> bool:
        if self._called:
            return False
        return elapsed >= SESSION_LIMIT.total_seconds() - CALL_BEFORE_SECS

    def called(self) -> None:
        self._called = True


def closer_from(
    panel: Sequence[Archetype],
    *,
    choose: Chooser = random.choice,
) -> tuple[Archetype, str]:
    """Who calls time, and how they put it.

    Drawn from the seated panel because a voice belonging to nobody at the
    table would be a narrator, and `choose` injected so a room can be repeated
    and measured — the same two reasons `opener_from` and `nudge_from` give.
    Custom archetypes carry no closers, which is one more reason every room
    seats at least one shipped archetype (`docs/custom-archetypes.md`).
    """
    speaking = [one for one in panel if one.closers]
    if not speaking:
        raise NoOneToOpen("no seated archetype can call time")

    who = choose(speaking)
    return who, choose(who.closers)
