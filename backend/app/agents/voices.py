"""The voices a panelist can be cast in, named in our own vocabulary.

**Never a vendor identifier.** Shipped archetypes are configuration in one file,
so swapping synthesis vendors there would be a find-and-replace — but a Pro
user's custom archetype is a row they own, and a vendor id stored in one turns
that swap into a migration over customer content. Same rule as `user_id` never
being a foreign key to `auth.users`: the cheap moment to avoid the coupling is
before any row exists.

A character rather than a person. `MEASURED` describes how somebody sounds, so a
custom archetype can be cast in it without inheriting anything about the shipped
archetype that happens to share it — and a better voice for "measured" arriving
next year is one line in an adapter, not a change to anybody's saved panel.

Eight, matching the eight shipped archetypes, because casting them established
the vocabulary. Adding a ninth means adding a vendor voice behind it in every
adapter, which `test_voice_casting.py` enforces.
"""

from __future__ import annotations

from enum import StrEnum


class Voice(StrEnum):
    """How a panelist sounds. The stored value is the member's string."""

    #: Unhurried and formal. Says less than it could.
    MEASURED = "measured"

    #: Careful and exact. Explains rather than asserts.
    PRECISE = "precise"

    #: Steady and credible. Sounds like it has decided.
    ASSURED = "assured"

    #: Fast and forward-leaning. Runs slightly ahead of the room.
    EAGER = "eager"

    #: Clipped and impatient. Sounds like it is late for something.
    BRISK = "brisk"

    #: Even and unhurried, and never quite says the whole thing.
    SMOOTH = "smooth"

    #: Open and direct. The easiest of them to listen to.
    WARM = "warm"

    #: Older and flat. Reads the caveat rather than the headline.
    DRY = "dry"


#: Everything a panelist may be cast in, shipped or custom.
#:
#: One set rather than two: a custom archetype chooses from exactly what the
#: shipped ones use, so nothing about a user's room sounds second-class. Panel
#: assembly is what keeps two seated panelists from sharing one — the constraint
#: is per-room, not per-library, and two custom archetypes never seated together
#: may safely share a voice.
CASTABLE: frozenset[Voice] = frozenset(Voice)
