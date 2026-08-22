"""How the panel is receiving the argument, read from what the room already did.

`Product.md` §3.4 asks for *"a directional read on how the panel is receiving the
argument"*. `CLAUDE.md` fixes the words and forbids the retired one: neutral and
transferable — **Convinced / Skeptical / Losing the room** — never "Investable →
Delusional", which does not survive outside a pitch.

The committed interrogation brief makes this the safelight itself: *"Convinced
warms and lifts the amber; Skeptical is neutral; Losing the room cools and dims
toward gray. No gauge, no needle, no number."* So what this returns is a band and
never a score, because a number on this screen would be the delivery-metrics
product §1 exists to refuse.

**No model call, and that is a measurement rather than a preference.** Asked
*"did the presenter dodge?"* a model said yes on 4 of 4 dodges **and** 4 of 4
genuine answers (#43) — the finding `agents/difficulty.py` cites as the reason
the difficulty dial is two integers and not an adjective. A temperature gauge is
that same question in a friendlier coat, and it would be asked once per turn,
eight to fifteen times a room, on the *metered* path whose margins §4.3 has not
yet reconciled against an invoice. A judgement nobody can trust, billed per room.

**So it is read from the one thing the room computes that is an event rather than
an opinion.** `Said.chosen_by == "finding"` means the Auditor caught the answer
before this line: a figure that moved between the deck and the spoken claim, or a
claim that contradicts one made earlier in the same room. Nothing about it is a
verdict on how well somebody argued — it is the record that two things they said
did not agree. `weakness.py` already ranks on exactly this signal, and
`docs/difficulty-calibration.md` already calibrates on it; this is the same fact
read live.

**Errs warm, on purpose.** #74 names the harmful failure precisely: telling
somebody they are losing the room while they are doing well, mid-session, when
they cannot argue back. Every asymmetry below leans away from that.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from app.agents.context import USER, Said


class Temperature(StrEnum):
    """The three bands, in the product's own words.

    Values are what goes on the wire. `losing_the_room` rather than `losing`
    because the phrase is the vocabulary `CLAUDE.md` fixed, and a client that
    received a shorter word would be free to render a different sentence.
    """

    CONVINCED = "convinced"

    #: The resting value, and deliberately not a fourth "unknown" band.
    #:
    #: A panel opens unconvinced — that is what the product is — so a room with
    #: too few turns to read is not lying when it says this. It is also what
    #: lets the screen open in its resting state instead of holding a colour
    #: back until it has earned one.
    SKEPTICAL = "skeptical"

    LOSING = "losing_the_room"


#: How many recent challenges a cooling read is taken over.
#:
#: Turns rather than seconds, because the room's clock is turns: a twelve-minute
#: room runs eight to fifteen of them, and a window in seconds would read four
#: challenges from a fast exchange and one from a long answer.
WINDOW = 4

#: Catches inside `WINDOW` before the room is being lost.
#:
#: Two, not one. Everybody gets a figure wrong, and a gauge that swung on the
#: first one would spend most rooms in the worst band it has.
CAUGHT_TO_COOL = 2

#: Consecutive clean challenges before the panel reads as convinced.
#:
#: **Longer than the cooling window, and the asymmetry is the argument.** Being
#: caught is evidence; *not* being caught is the absence of evidence, and absence
#: is cheap early — `docs/auditor-grounding.md` has the deckless room checking
#: new speech against a reference that is still accumulating, so the first few
#: turns of any room without material are structurally quiet. Handing out
#: "convinced" for that would be the gauge congratulating somebody for a silence
#: it caused.
#:
#: Six is most of a short room and half a long one, so it is reachable and
#: earned. It is a judgement, and a small one.
CLEAN_TO_WARM = 6


def temperature_of(transcript: Sequence[Said], *, was: Temperature) -> Temperature:
    """The band this room is in now, given the band it was in.

    **Derived, never stored** — the rule `orchestrated._attention` already
    follows for the same reason. A remembered temperature is stranded by every
    path that fails: a turn that dies would leave the room asserting a mood for
    the rest of the session, and a confidently wrong safelight is worse than a
    steady one.

    `was` is the previous band rather than internal state, which is what makes
    the hysteresis testable and the function pure. Two callers derive this — the
    transition points and the heartbeat — and they must never disagree about the
    same instant; they cannot, if neither of them remembers anything.
    """
    challenges = _challenges(transcript)

    # Nothing has been received yet. The opening floor (#79) is the presenter
    # making their case before anybody challenges it, and a room can also simply
    # be three turns old.
    #
    # Above the hysteresis rather than below it, and it costs nothing: a
    # transcript only grows, and no band but the resting one is reachable
    # without `WINDOW` challenges having already happened. There is no room that
    # was convinced and now has three turns.
    if len(challenges) < WINDOW:
        return Temperature.SKEPTICAL

    caught = sum(1 for line in challenges[-WINDOW:] if line.chosen_by == "finding")

    if was is Temperature.LOSING:
        # One clean turn after two catches is not a recovery. Treating it as one
        # would flip the safelight on alternate turns for the rest of the room,
        # which is the noise #74 asks this not to be.
        return Temperature.SKEPTICAL if caught == 0 else Temperature.LOSING

    if was is Temperature.CONVINCED:
        # Fast, where warming was slow. The presenter has just heard a panelist
        # quote a figure back at them; a screen still saying the room is
        # persuaded would be arguing with what they can hear.
        return Temperature.SKEPTICAL if caught else Temperature.CONVINCED

    if caught >= CAUGHT_TO_COOL:
        return Temperature.LOSING

    # Every route between the extremes passes through here — a convinced room
    # cools to neutral first and can only be lost from neutral, which is also
    # what holds a twelve-minute room to two or three changes rather than one
    # per turn.
    clean = challenges[-CLEAN_TO_WARM:]
    if len(clean) == CLEAN_TO_WARM and not any(
        line.chosen_by == "finding" for line in clean
    ):
        return Temperature.CONVINCED

    return Temperature.SKEPTICAL


def _challenges(transcript: Sequence[Said]) -> list[Said]:
    """The panel lines this reading is entitled to be taken over.

    The presenter's own lines are not a reading of how the presenter is doing.

    **Disputes are excluded rather than counted either way**, which is #56's rule
    applied live: a question waved away by a colleague is unanswered and not the
    presenter's fault, and the debrief already refuses to rank it against them.
    Counting one as a catch would tell somebody they are losing a room they were
    not allowed to answer in; counting one as clean would let a room that argued
    with itself warm on turns the presenter never spoke in.

    Nothing is lost by dropping them. `panel.interrogate` sets
    `dispute = None if finding else contested(...)`, so a line can be a catch or
    a dispute and never both.
    """
    return [
        line
        for line in transcript
        if line.speaker != USER and not line.disputed
    ]
