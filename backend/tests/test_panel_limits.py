"""How many people a plan puts in the room, and who may write their own.

Panel size is a **product** lever here rather than a cost one, and that is worth
stating because it inverts the usual reasoning. Only one archetype speaks per
turn — the selection step reads the roster, the composer reads one persona — so a
five-person panel costs almost exactly what a three-person panel costs. Nothing
about this cap protects a margin.

What it protects is the session. A ten-minute interrogation split six ways gives
everybody two questions and nobody a line of attack that goes anywhere, so a
bigger room is not a better one past a point. The tiering sells assembling a room
rather than crowding one.
"""

from __future__ import annotations

import pytest

from app.agents.archetypes import DEFAULT_PANEL, LIBRARY
from app.agents.panel import assemble
from app.core.errors import ArchetypeNotFound, PanelTooLarge
from app.modules.billing.tiers import (
    FREE_TIER,
    UPGRADE_LADDER,
    max_panel_size,
    may_author_archetypes,
)


def names(*archetypes) -> list[str]:
    return [archetype.name for archetype in archetypes]


def test_a_free_account_gets_three_seats():
    """Three is the floor and the shipped room, not a degraded version of one.

    §3.1's mixed panel — a champion, a skeptic and a neutral — fits in three, so
    the free tier gets a complete experience rather than a taste of one. §4.4:
    *"the free tier gives one complete experience, not three truncated tastes."*
    """
    panel = assemble(tier="free", chosen=names(*LIBRARY[:3]))

    assert len(panel) == 3


def test_a_free_account_cannot_seat_a_fourth():
    """The refusal names the plan that would take it, like every other cap here.

    `MaterialTooLarge` set the pattern: a limit the user hits is also the one
    honest moment to say what would lift it. A bare "too many" is a dead end.
    """
    with pytest.raises(PanelTooLarge) as refused:
        assemble(tier="free", chosen=names(*LIBRARY[:4]))

    assert "Starter" in refused.value.message


def test_the_free_room_seats_the_panel_we_ship():
    """A structural tie, not a coincidence, and it binds two files.

    `DEFAULT_PANEL` is what a session gets when nobody chooses, and the free cap
    is what a free account may seat. If the default ever grew to four, every free
    user would be refused the room the product hands them by default — a first
    session that fails before it starts, on the tier where first sessions happen.
    """
    assert max_panel_size(FREE_TIER) >= len(DEFAULT_PANEL)


def test_every_shipped_archetype_has_been_cast():
    """A panelist without a voice falls back to the house one and sounds like
    everybody else.

    That is the correct behaviour for a *custom* archetype — a Pro user writes a
    persona, not a voice — but for one we ship it is a casting job somebody
    forgot. The failure is quiet and only audible on a device: the room still
    runs, still routes, still challenges, and two of the panelists happen to be
    indistinguishable. On a hands-free surface where the phone is face-down,
    voice is the only signal of who is speaking, so that is the whole panel
    collapsing into one person with four opinions.
    """
    mute = [archetype.name for archetype in LIBRARY if not archetype.voice]

    assert mute == [], f"archetypes shipping without a voice: {mute}"


def test_no_two_archetypes_share_a_voice():
    """Two panelists with one voice is worse than one panelist.

    The user cannot tell them apart, so a disagreement between them — which
    §3.3 treats as a feature of a real room — reads as a single person
    contradicting themselves.
    """
    voices = [archetype.voice for archetype in LIBRARY]

    assert len(set(voices)) == len(voices)


def test_the_ladder_never_goes_backwards():
    """Paying more may buy the same room; it must never buy a smaller one.

    Cheap to assert and easy to break, since these are four numbers in a dict
    that somebody will one day edit while thinking about something else.
    """
    seats = [max_panel_size(tier) for tier in UPGRADE_LADDER]

    assert seats == sorted(seats)


def test_teams_sits_with_starter():
    """§4.4 prices Teams at Starter level per seat and refuses to undercut the
    standalone plan. Every other capability in `tiers.py` follows that — upload
    size, page cap, monthly allowance — and a room that quietly differed would be
    a pricing inconsistency nobody decided.
    """
    assert max_panel_size("teams") == max_panel_size("starter")


def test_writing_your_own_panelist_starts_at_pro():
    """§4.4 sells custom archetypes as a Pro capability.

    Unlike panel size this is a real differentiator, because it is the one panel
    feature that is not simply a number — and it is the one with a design still
    owed, since a user-authored persona is where the removed real-person
    simulation could walk back in through the front door.
    """
    assert not may_author_archetypes("free")
    assert not may_author_archetypes("starter")
    assert may_author_archetypes("pro")
    assert may_author_archetypes("pro_annual")


def test_a_panelist_nobody_answers_to_is_refused_rather_than_skipped():
    """Seating a smaller room than the user assembled is the worse failure.

    They would discover it by noticing somebody never spoke, which reads as a
    broken panel rather than as a rejected request — and they would have no idea
    which name was the problem.
    """
    with pytest.raises(ArchetypeNotFound):
        assemble(tier="pro", chosen=["cfo", "the_ghost_of_warren_buffett"])


def test_the_size_check_answers_before_the_names_do():
    """Asked for six, told about six — not about a name we never reached.

    A user who assembles an over-large room asked a question about size. Refusing
    on the third unrecognised name instead would answer a question they did not
    ask, and hide the one they did.
    """
    with pytest.raises(PanelTooLarge):
        assemble(tier="free", chosen=["nobody"] * 6)
