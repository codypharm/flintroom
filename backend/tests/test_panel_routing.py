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
from app.agents.panel import Asked, Grounding, TurnContext
from app.agents.routing import choose


def context(said: str, *asked: Asked) -> TurnContext:
    return TurnContext(said=said, grounding=Grounding(asked=tuple(asked)))


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
        context(said, Asked(archetype="cfo", question="Which number is lying?")),
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
    history = (Asked(archetype="cfo", question="Which number is lying?"),)

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
