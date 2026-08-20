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

import re

import pytest

from app.agents.archetypes import DEFAULT_PANEL, LIBRARY, by_name
from app.agents.routing import _domain_hits
from app.agents.vocabulary import DOMAIN_TERMS, terms_for
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


def test_every_shipped_archetype_says_how_it_speaks():
    """Cadence is the only expressive channel the synthesis model gives us.

    Measured against the live account: Flash v2.5 cannot perform audio tags — it
    reads them aloud — so nothing about sighs, pauses or emphasis is available.
    What survives synthesis is *the shape of the sentence*: how long it runs,
    where the full stops fall, whether it opens with a beat.

    Three of the eight personas happened to mention delivery and five did not,
    which meant the Distracted Executive sounded exactly like the Risk Officer
    saying different words. This makes it deliberate for all of them, and a
    separate field from `persona` for the reason `attack_strategy` is separate:
    who somebody is, what they attack, and how their words land change for
    different reasons, and tuning one should not disturb the others.
    """
    silent = [archetype.name for archetype in LIBRARY if not archetype.cadence]

    assert silent == [], f"archetypes with no delivery described: {silent}"


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


def test_every_domain_is_reachable_without_software_words():
    """The rule this file's own LIBRARY docstring states, made checkable.

    *"personas describe a stance, and never an industry. 'Attacks the numbers'
    works in a board room, a client meeting and a sprint review; 'asks about
    your cap table' works in one."*

    Seven of the eight obeyed it. The Technical Skeptic did not — her domains
    were `technology`, `architecture`, `security`, reachable only by software
    words, and her strategy named "a competitor with more ENGINEERS". Seated
    against a medical supply business she had nothing legitimate to ask, so she
    reached for the nearest technical noun and invented one (#81).

    **The fix is not to take the software words away.** She has to stay sharp
    on a deployment when the subject IS a deployment. What she cannot be is
    reachable ONLY that way — so every domain must also answer to words a
    business with no software in it would use.
    """
    SOFTWARE = {
        "server", "servers", "database", "api", "code", "deployment", "cloud",
        "latency", "stack", "engineering", "infrastructure", "architecture",
        "uptime", "outage", "release", "soc", "penetration", "vulnerability",
        "technology", "tech", "security", "breach",
    }

    for archetype in LIBRARY:
        for domain in archetype.domains:
            terms = set(terms_for(domain))
            assert terms - SOFTWARE, (
                f"{archetype.name}'s domain {domain!r} can only be reached by "
                f"software words: {sorted(terms)}"
            )


def test_the_skeptic_is_reachable_by_a_business_with_no_software_in_it():
    """A medical supply business has everything she is for.

    Does this actually work, what breaks when volume triples, what could a
    better-resourced rival copy in a quarter — all of it applies to a cold
    chain. She simply could not say any of it while she was defined in servers.
    """
    supply = (
        "We ship refrigerated vaccines to forty clinics. Two suppliers, one "
        "warehouse, and delivery takes about a day."
    )

    assert _domain_hits(by_name("technical_skeptic"), supply) > 0


def test_the_skeptic_is_still_sharpest_when_the_subject_is_software():
    """And the other half, which is the reason not to simply de-technicalise her.

    Generalising her must not cost the case she was built for. Against a
    deployment she should still be the most obviously relevant person at the
    table.
    """
    build = (
        "We deploy twice a week. The API sits behind a load balancer and the "
        "database is replicated across two regions."
    )
    skeptic = _domain_hits(by_name("technical_skeptic"), build)

    assert skeptic > 0
    assert skeptic >= max(
        _domain_hits(one, build) for one in LIBRARY if one.name != "technical_skeptic"
    )


def test_no_word_signals_two_domains_at_once():
    """A word in two lists is routed by whichever key comes first in a dict.

    That is not a decision anybody made, and it is invisible: routing keeps
    working, it simply picks a different panelist than the table appears to say.
    `capacity` was the first collision — generalising the Technical Skeptic gave
    her a domain whose canonical name the Internal Blocker already listed under
    `resourcing`, and she silently took every "we are at capacity" with her.

    Resolved in the table rather than by ordering: she keeps the word, the
    Blocker keeps `bandwidth`. This is what stops the next one being silent.
    """
    owner: dict[str, str] = {}

    for domain, terms in DOMAIN_TERMS.items():
        for term in terms:
            assert term not in owner, (
                f"{term!r} signals both {owner[term]!r} and {domain!r} — "
                f"routing picks one by dict order rather than by decision"
            )
            owner[term] = domain


#: A definite article naming a thing in the presenter's business, in the same
#: breath as saying they never mentioned it.
NAMES_THE_UNMENTIONED = re.compile(
    r"\bthe\s+[\w\s'-]{0,40}?\bnobody\s+(?:ever\s+)?mentioned\b", re.IGNORECASE
)


def test_no_archetype_is_told_to_name_what_nobody_mentioned():
    """#63 — the CFO ignored a prohibition the other seven obey.

    `_persona_prompt` forbids asserting a fact the presenter did not supply, and
    names the tell: *"the tell is the word THE. Do not say 'the architecture',
    'the pipeline' ... Naming a thing that way tells them it exists, and you do
    not know that it does."*

    The CFO's own strategy told it to do exactly that. It listed targets — *"Unit
    economics, margin at scale, the cost line nobody mentioned, the growth rate
    ..."* — a definite article naming a line in their books while stating outright
    that they never mentioned it. **No model failure: the configuration
    contradicted the instruction beneath it**, and the archetype obeyed the half
    written in its own voice.

    The other seven phrase the same idea as a question, which the prompt blesses
    in as many words — *"A question you cannot answer yourself is the strongest
    thing you can say."* The Skeptic asks *which* single point of failure nobody
    has named; the Risk Officer asks *which* approval has not been obtained. An
    interrogative asks whether a thing exists. A noun phrase asserts it does.

    **Narrow on purpose.** This pins the construction that shipped, not a general
    theory of presupposition — no regex can separate "the case nobody wants to
    discuss", a category every plan has, from "the cost line nobody mentioned",
    a specific claim about somebody's accounts.
    """
    for archetype in LIBRARY:
        assert not NAMES_THE_UNMENTIONED.search(archetype.attack_strategy), (
            f"{archetype.name} is told to name something unmentioned"
        )
        assert not NAMES_THE_UNMENTIONED.search(archetype.persona), archetype.name
