"""How hard the room pushes this particular person.

`docs/difficulty-calibration.md`. `CLAUDE.md` states the requirement in one
line — *"a first session that destroys the user produces churn, not
resilience"* — and it sits under Open Risk #1, which is that being attacked at
all is the riskiest assumption in the product.

**Two integers, and nothing in a prompt.** The dial is the press cap and the
dispute budget, both already enforced by code. Nothing here touches an
archetype: `persona`, `attack_strategy` and `cadence` are who somebody *is*,
and a person does not become a different person because you have had four
sessions.

The reason it is integers is a measurement rather than a preference. Asked
*"did the presenter dodge?"* a model said yes on 4 of 4 dodges and 4 of 4
genuine answers (#43); asked to weigh three selection criteria joined by "or"
it took the easiest and gave the CFO 7 of 8 turns (`scripts/rotation.py`). A
difficulty dial written as an adjective — "go gently", "give them nothing" — is
the same shape that has now failed here twice. It would also make a level
irreproducible, and `scripts/rotation.py` cannot measure a room that is not the
same room twice.
"""

from __future__ import annotations

from typing import NamedTuple

#: How many turns in one room may open by disputing a colleague.
#:
#: **Here rather than in `dispute.py`, and only because of the import graph.**
#: `context.TurnContext` carries a `Pressure`, so this module may not import
#: anything from the agents package that imports `context` — and `dispute` does.
#: The number's reasoning is unchanged and worth keeping next to it:
#:
#: A room is capped at twelve minutes and runs perhaps eight to fifteen turns,
#: so two is a seasoning rather than a texture. It is a judgement and
#: deliberately a small one: the failure it guards against — a room that argues
#: with itself while the presenter waits — is worse than the failure of it never
#: happening, because only one of those stops the product interrogating.
DISPUTES_PER_ROOM = 2


class Pressure(NamedTuple):
    """What one rung of the ladder actually sets.

    A pair rather than a level passed around, so that nothing downstream has to
    know the ladder exists. `dispute.contested` wants a budget and the selection
    prompt wants a cap; neither should be looking up a user's history to find
    one.
    """

    #: How many consecutive turns a panelist may spend pressing its own
    #: unanswered question. **Never zero**, at any rung.
    presses: int

    #: How many turns in the room may open by disputing a colleague's
    #: priorities. Zero at the floor, which is what "gentle" means here.
    disputes: int


#: The rungs, gentlest first.
#:
#: **Every number is either today's shipped figure or zero.** That is why there
#: are three and not four: a fourth would have to invent one, and `dispute.py`
#: chose two deliberately on the ground that *"two is a seasoning rather than a
#: texture"* in a room of eight to fifteen turns. Fake precision on a dial
#: nobody can perceive is worse than a short ladder.
#:
#: **`presses` never reaches zero, and that is load-bearing.** An earlier draft
#: of `_SELECTION_INSTRUCTION` forbade consecutive turns outright and its own
#: docstring records why that was wrong: *"It gave up the sharpest move a room
#: has — the person who asked something noticing it was not answered."* A
#: level-1 room with no press is not a gentle version of this product, it is a
#: room that has stopped doing the thing the wedge is made of, shipped to the
#: one session that has to sell it.
#:
#: So the floor softens the *disputes* instead. Being cut across by a colleague
#: is the mildly dismissive turn #54 introduced, and a first-timer talked over
#: by two panelists is exactly the line `Product.md` §434 draws: *"Hostility is
#: the product; humiliation is the churn."*
LADDER: tuple[Pressure, ...] = (
    Pressure(presses=1, disputes=0),
    Pressure(presses=1, disputes=DISPUTES_PER_ROOM),
    Pressure(presses=2, disputes=DISPUTES_PER_ROOM),
)

#: The rung a new account starts on, and the one a bad session falls back to.
GENTLE = 1

#: The room that ships today. Read from `DISPUTES_PER_ROOM` rather than written
#: out, so that changing the shipped cap moves this rung with it.
STANDARD = 2

RELENTLESS = 3


def pressure_at(level: int) -> Pressure:
    """The rung, for any integer at all.

    Clamped rather than validated, because the caller is the live
    interrogation path. A row holding 7 — a bad migration, a future rung
    removed, an admin fat-finger — must produce a real room rather than end a
    metered session over bookkeeping. The same call `_usage_of` makes in the
    panel adapter, for the same reason.
    """
    return LADDER[min(max(level, GENTLE), len(LADDER)) - 1]


#: The room that ships today, as a value.
#:
#: Every default in the codebase points here rather than at `LADDER[1]`, so
#: that "level 2 is byte-identical to what shipped" is enforced by there being
#: one object rather than by two lists agreeing. A caller that never heard of
#: calibration gets exactly the room `scripts/rotation.py` measured.
STANDARD_PRESSURE = LADDER[STANDARD - 1]
