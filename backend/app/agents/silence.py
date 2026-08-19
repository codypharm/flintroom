"""What the room says when nobody has said anything for a while.

#24, and the last of the five things that look like silence to somebody sitting
in a room that has gone quiet: it is thinking, it did not hear them, it is
waiting for more, it has failed, or **it is about to end**. `Attending` tells
the first three apart on the screen and the debrief's refusals cover the fourth.
This one cannot be shown.

**Spoken, and that is the whole point.** #24 argued it before the architect
chose it: the phone is face-up on a desk, and a visual warning "arrives at the
moment attention is lowest, aimed at someone who has by definition stopped
looking". The person this exists for has turned away to find a figure, or is out
of the room entirely, or is holding a dead microphone. None of them can see the
screen. Only sound reaches them.

It changes nothing about the clock, and that is deliberate — see `Silence`.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from app.agents.archetypes import Archetype
from app.agents.opening import Chooser, NoOneToOpen


#: How long the room lets the quiet run before asking whether anybody is there.
#:
#: `IDLE_LIMIT` is ninety seconds and the meter sweeps every fifteen, so a room
#: actually ends somewhere between ninety and a hundred and five. Sixty leaves
#: at least twenty-five seconds to answer and keep it.
#:
#: **Chosen against a real tension rather than picked.** Two different people go
#: quiet and they want opposite things. Somebody thinking hard about a question
#: they did not expect is doing exactly what the room asked — `IDLE_LIMIT`'s own
#: docstring calls ninety seconds "long enough to sit through a hostile question
#: and think before answering" — and interrupting them is nagging. Somebody who
#: stepped away needs to hear it while there is still time to come back. Sixty
#: sits past the point where silence is still plausibly thought.
#:
#: Reasoned, not measured. The honest source is how long people actually pause
#: mid-interrogation, and `session_transcript_lines` timestamps every line, so
#: real rooms can settle it later. Worth revisiting rather than defending.
NUDGE_AFTER_SECS = 60.0


@dataclass
class Silence:
    """Whether this stretch of quiet has earned a question, and whether it got one.

    **It changes nothing.** Asking does not reset the idle clock and does not
    extend the limit — panel speech deliberately never counts as activity,
    precisely so that a room talking to an empty chair still ends. A warning
    that bought time would be a second clock, and a silent room could then run
    forever on somebody's invoice.

    So if nothing follows, the room ends at ninety exactly as it did before and
    refunds in full. #24 already accepted that trade: the cost of not warning is
    "surprise, not money". This removes the surprise and leaves the money alone.
    """

    #: Whether this stretch of quiet has already had its one question.
    _asked: bool = False

    def worth_asking(self, *, quiet_for: float) -> bool:
        """Long enough, and not yet asked.

        Once per stretch rather than once per room. Somebody who steps away,
        comes back, answers three questions and steps away again was present
        the whole time in between — refusing them a second question would make
        this useless for exactly the person it is for.
        """
        return not self._asked and quiet_for >= NUDGE_AFTER_SECS

    def asked(self) -> None:
        """Said once. A room that asks twice is a smoke alarm, not a room."""
        self._asked = True

    def heard(self) -> None:
        """They are back. The next stretch of quiet starts fresh."""
        self._asked = False


def nudge_from(
    panel: Sequence[Archetype], *, choose: Chooser = random.choice
) -> tuple[Archetype, str]:
    """Who asks whether anybody is there, and how they put it.

    The same shape as `opener_from` and for the same reasons: drawn from the
    **seated** panel because a voice belonging to nobody at the table would be a
    narrator, and `choose` injected so a room can be repeated and measured.

    Hand-written lines, never composed. Sharper here than for the opener: this
    is spoken to somebody who may have walked away from a room billing them by
    the minute, so it has to be short, unmistakable and the same every time it
    is heard. A composed line is none of those, and it would be a model call
    made about nothing at all.
    """
    speaking = [one for one in panel if one.nudges]
    if not speaking:
        raise NoOneToOpen("no seated archetype has a way to ask")

    who = choose(speaking)
    return who, choose(who.nudges)
