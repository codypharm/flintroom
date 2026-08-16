"""Choosing a speaker without spending a model call on it.

Measured, a model round trip for selection costs ~0.8s of a 1.5s budget — for a
decision that is mostly a lookup. `docs/panel-orchestration.md` records the
numbers and the choice: route in code, and spend the whole budget on the hop that
writes the line.

The routing is deliberately dumb. It matches an archetype's declared domains
against what was said and prefers whoever has been quiet. What it gives up is
comprehension — a model would understand an answer that never uses the word
"margin" but is entirely about margin. What it buys is the turn happening at all.
"""

from __future__ import annotations

from app.agents.archetypes import DEFAULT_PANEL, LIBRARY, by_name
from app.agents.panel import Grounding, Said, TurnContext
from app.agents.routing import choose


def context(said: str, *spoken: Said) -> TurnContext:
    return TurnContext(said=said, grounding=Grounding(transcript=tuple(spoken)))


def test_an_answer_about_the_numbers_reaches_the_numbers_person():
    """§3.3's rule, applied to ordinary turns rather than only to findings.

    The domains an archetype declares are the vocabulary it owns, so matching
    them against what was actually said is the cheapest honest signal available
    — and it is the same lookup `_owner` already uses to route an Auditor
    finding, widened to the case where there is no finding.
    """
    chosen = choose(DEFAULT_PANEL, context("Our gross margin is around seventy percent."))

    assert chosen.name == "cfo"


def test_the_person_who_just_spoke_yields_to_the_room():
    """Relevance beats rotation, but not indefinitely.

    A founder talks about money for two minutes. On domain match alone the CFO
    takes every single turn, which is not a panel — it is one person with an
    audience, and §3.1 ships a mixed room precisely to avoid that.

    So silence accumulates against relevance. The CFO wins the first margin
    question and loses the second to somebody who has not spoken at all.
    """
    said = "Our gross margin is around seventy percent."

    first = choose(DEFAULT_PANEL, context(said))
    second = choose(
        DEFAULT_PANEL,
        context(said, Said(speaker="cfo", text="Which number is lying?")),
    )

    assert first.name == "cfo"
    assert second.name != "cfo"


def test_an_answer_nobody_owns_still_gets_a_speaker():
    """The room is never silent, whatever was said.

    Most of what a presenter says touches no declared domain at all — narrative,
    context, an anecdote. If routing only fired on a keyword the panel would go
    quiet exactly when somebody is talking freely, which is the moment a room is
    most intimidating.
    """
    chosen = choose(DEFAULT_PANEL, context("Let me take you back to how we started."))

    assert chosen in DEFAULT_PANEL


def test_the_same_room_and_the_same_answer_choose_the_same_person():
    """Deterministic, so a bad transcript can be explained.

    A random tiebreak would make *"why did it ask that"* unanswerable, and it is
    the first question anybody asks about a room that went wrong.
    """
    said = "Our gross margin is around seventy percent."
    history = (Said(speaker="cfo", text="Which number is lying?"),)

    picks = {choose(DEFAULT_PANEL, context(said, *history)).name for _ in range(10)}

    assert len(picks) == 1


def test_a_domain_word_inside_another_word_is_not_a_match():
    """Whole words, because a substring check reads as cleverness and behaves as
    noise. `cost` should not fire on "costume", and `data` should not fire on
    "database" — which a deck about databases would trigger on every sentence,
    handing the room permanently to the Risk Officer.
    """
    risk = by_name("risk_officer")
    assert "data" in risk.domains

    # The champion goes first so declaration order favours *it* on a tie. A
    # substring match would give the Risk Officer a domain hit worth three points
    # and it would win anyway — which is exactly what this needs to be able to
    # detect. Ordered the other way the assertion passes either way and proves
    # nothing, which is how it was written first.
    chosen = choose(
        (by_name("champion"), risk),
        context("Our database migration is finished."),
    )

    assert chosen.name == "champion"


def test_the_numbers_person_hears_unit_economics_without_the_word():
    """Measured, one canonical word per domain routed 7% of realistic utterances.

    "We're spending more to acquire each customer than we make back" is textbook
    CFO and contains none of `margin`, `revenue`, `cost`. So did most of a
    fifteen-sentence sample: `ARR` is revenue, `the team is eight people` is
    headcount, `SOC 2` is compliance. The domains named the right concepts and
    then listened for exactly one spelling of each.

    Without this the panel is round-robin with an occasional coincidence, which
    is the mechanical failure §3.3 calls synthetic within two minutes.
    """
    # The CFO goes last so declaration order works *against* it: with nothing
    # matching, everything ties on silence and the first archetype wins. Ordered
    # the other way this passes without routing anything, which is how it was
    # written first.
    panel = (by_name("champion"), by_name("technical_skeptic"), by_name("cfo"))

    chosen = choose(
        panel,
        context("We're spending more to acquire each customer than we make back."),
    )

    assert chosen.name == "cfo"


def test_a_domain_with_no_vocabulary_still_answers_to_its_own_name():
    """Archetypes are configuration, so somebody adds one before its words.

    A domain absent from the table falls back to matching the canonical name —
    the behaviour before the table existed. Degrading to the old routing is
    acceptable; degrading to silence, where a new archetype never speaks and
    nothing says why, is not.
    """
    from app.agents.vocabulary import terms_for

    assert terms_for("a_domain_nobody_has_written_words_for") == (
        "a_domain_nobody_has_written_words_for",
    )


def test_every_archetypes_domains_have_words_people_actually_say():
    """A domain with no entry routes on one spelling, which measured 7%.

    Cheap to assert and easy to forget: the vocabulary lives in a different file
    from the archetypes, so adding a panelist and adding its words are two
    separate acts and only one of them is obvious.
    """
    from app.agents.vocabulary import DOMAIN_TERMS

    missing = [
        domain
        for archetype in LIBRARY
        for domain in archetype.domains
        if domain not in DOMAIN_TERMS
    ]

    assert missing == []
