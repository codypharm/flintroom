"""The meeting somebody described, turned into a room.

`docs/onboarding.md` asks five questions and promises the answers configure the
product. This is the file that keeps the promise: the chips a user tapped onto
their seating plan become the archetypes who will be in the chairs.

**A lookup, never a model call.** The doc's testing note wants *"an assertion on
the archetypes selected for a given answer set"*, and that sentence is only
writable if the mapping is deterministic. It is also the third time this project
has reached the same conclusion by measurement: asked *"did the presenter
dodge?"* a model said yes on 4 of 4 dodges and 4 of 4 genuine answers (#43), and
asked to weigh three selection criteria it gave the CFO 7 of 8 turns
(`scripts/rotation.py`). Composition is an extraction, not a judgement, so it is
a table.

**The chips are in the user's vocabulary, not ours.** Nobody plans a meeting by
thinking "I need a Margin-Obsessed CFO"; they think "whoever controls the
budget". Naming the chips after the archetypes would turn the survey into a
panel picker and the reveal into an echo — the user would be choosing their own
room and then being shown it back. The translation *is* the payoff.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.agents.archetypes import DEFAULT_PANEL, Archetype, by_name

#: What each seat on the plan means, and who fills it.
#:
#: Seven chips against eight archetypes. `growth_maximalist` is deliberately
#: absent: "somebody who will push you on market size and why now" is not a
#: person anybody pictures around their own table — it is a stance a room takes,
#: and it arrives through the asker's own role instead.
SEATING: dict[str, str] = {
    "budget": "cfo",
    "technical": "technical_skeptic",
    "ally": "champion",
    "distracted": "distracted_executive",
    "compliance": "risk_officer",
    "customer": "customer_advocate",
    "rival": "internal_blocker",
}


#: Who else is usually in that room, by the asker's own role.
#:
#: Product.md §2 is the reason role fills rather than a generic remainder: a
#: product manager defending a roadmap and a founder at demo day face
#: structurally different tables, and once the chips agree, role is the only
#: answer left that separates them.
#:
#: Read strictly in order and only for chairs still empty. This is a completion
#: of somebody's plan, never a correction of it.
BY_ROLE: dict[str, tuple[str, ...]] = {
    #: Board readouts, exec updates, QBRs, steering committees.
    "exec": ("cfo", "internal_blocker", "distracted_executive"),
    #: Launch reviews, roadmap defences, budget and headcount requests.
    "pm": ("internal_blocker", "technical_skeptic", "customer_advocate"),
    #: Contract bids, client defences, renewals.
    "consultant": ("cfo", "customer_advocate", "risk_officer"),
    #: Angel, seed, venture, demo day — the only room that seats the Growth
    #: Maximalist, since "why now, and how big" is a stance a funding table
    #: takes rather than a person anybody pictures at their own.
    "founder": ("growth_maximalist", "cfo", "technical_skeptic"),
    #: Thesis defence, viva, conference Q&A. The CFO earns its chair here on
    #: its own words — *"never accept a figure without its basis"* is an
    #: examiner as much as an accountant.
    "student": ("technical_skeptic", "cfo", "champion"),
}


def compose(
    *, audience: Sequence[str], role: str | None, seats: int
) -> tuple[Archetype, ...]:
    """The room, from the plan somebody filled in.

    Order is preserved because the plan is a seating chart. Somebody put a
    person in the first chair, and a room that quietly re-sorts them has
    stopped being the thing they filled in.
    """
    # Unknown chips are dropped, not refused. This runs at sign-up, at the end
    # of a flow the user has just spent five answers on, and an app one release
    # ahead of the server would otherwise cost them the account rather than a
    # chair. Safe because the reveal renders from what was seated here, so what
    # they are shown is always the room they will actually get.
    chosen = [SEATING[chip] for chip in audience if chip in SEATING]

    # Role first, then the shipped default. The default is last because it is
    # the answer to "we know nothing about this meeting", and role is something
    # we do know.
    for name in (
        *BY_ROLE.get(role or "", ()),
        *(archetype.name for archetype in DEFAULT_PANEL),
    ):
        if len(chosen) >= seats:
            break
        if name not in chosen:
            chosen.append(name)

    return tuple(by_name(name) for name in chosen[:seats])
