"""The unit a figure is in, decided by code rather than by a model.

`docs/auditor-grounding.md`: *"most false positives come from comparing figures
that were never comparable"* — and a false accusation is worse than a missed
catch, because a panel that pounces on a unit mismatch is not intimidating, it is
stupid. So the unit is a closed set, and turning whatever a model wrote into a
member of that set is ordinary code: the same *"the model extracts, code
computes"* split that makes arithmetic hallucination impossible rather than
discouraged.

Tested with no model in the loop, which is the point. If this needed one, the
split has leaked.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.ingestion.schemas import (
    AssertionClaim,
    ClaimKind,
    QuantitativeClaim,
    Unit,
    normalize_unit,
)


def claim(**overrides) -> QuantitativeClaim:
    return QuantitativeClaim(
        **{
            "metric": "gross margin",
            "value": 61.0,
            "unit": "%",
            "period": "Q3 2026",
            "quote": "Gross margin held at 61% in Q3.",
            **overrides,
        }
    )


def assertion(**overrides) -> AssertionClaim:
    return AssertionClaim(
        **{
            "subject": "distribution",
            "statement": "Exclusive distribution agreement with Walmart.",
            "quote": "Exclusive distribution — Walmart, signed Q2.",
            **overrides,
        }
    )


@pytest.mark.parametrize("written", ["%", "percent", "PCT", " percentage "])
def test_a_percentage_is_one_unit_however_it_was_written(written):
    """Four spellings of the same thing, and a model will produce all four.

    Left as written, `61 "%"` and `61 "percent"` are two incomparable figures,
    so a margin restated in different words reads as a contradiction that is not
    there — the false positive this whole layer exists to prevent.
    """
    assert normalize_unit(written) is Unit.PERCENT


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("$", Unit.USD),
        ("USD", Unit.USD),
        ("dollars", Unit.USD),
        ("€", Unit.EUR),
        ("GBP", Unit.GBP),
    ],
)
def test_a_currency_becomes_its_code(written, expected):
    """Symbols and names collapse onto the code, and currencies stay distinct.

    Distinct because they genuinely are: €4M and $4M are not the same claim, and
    a normaliser that flattened both to "currency" would invent an agreement
    between them.
    """
    assert normalize_unit(written) is expected


@pytest.mark.parametrize("written", ["x", "×", "times", "8x"])
def test_a_multiple_is_its_own_unit(written):
    """A revenue multiple is not a count and not a percentage.

    It is the unit the sharpest derived catch in the product is expressed in —
    the 200× multiple somebody claimed out loud without noticing — so collapsing
    it into anything else loses that check.
    """
    assert normalize_unit(written) is Unit.MULTIPLE


@pytest.mark.parametrize("written", ["furlongs", "", "  ", "widgets per fortnight"])
def test_an_unrecognised_unit_stays_unknown_rather_than_being_guessed(written):
    """Deny by default, applied to arithmetic.

    Guessing produces the comparison that should never have happened, and
    silently. `unknown` is honest and it is inert: nothing compares to it, so an
    unrecognised unit costs a missed catch rather than a false accusation — the
    direction `docs/auditor-grounding.md` says to err in.
    """
    assert normalize_unit(written) is Unit.UNKNOWN


def test_a_claim_normalises_its_unit_on_the_way_in():
    """The type carries the guarantee, so no caller can forget to apply it.

    A free-standing normaliser is one somebody constructs a `Claim` without
    calling, and the failure is invisible until two figures that should have
    matched do not.
    """
    assert claim(unit="percent").unit is Unit.PERCENT
    assert claim(unit="%").unit is Unit.PERCENT


def test_two_unknown_units_are_not_thereby_comparable():
    """`unknown` is not a unit two figures can share.

    The subtle version of the guessing failure: normalising everything unknown
    to one token makes "furlongs" and "widgets" agree. Comparability is asked as
    a question rather than inferred from equality, so the answer is no.
    """
    furlongs = claim(unit="furlongs")
    widgets = claim(unit="widgets")

    assert furlongs.unit is widgets.unit is Unit.UNKNOWN
    assert not furlongs.comparable_to(widgets)


def test_two_figures_in_the_same_unit_and_period_are_comparable():
    """The case the Auditor exists to act on."""
    assert claim(value=61.0).comparable_to(claim(value=25.0))


def test_figures_from_different_periods_are_not_comparable():
    """Last quarter's revenue against last year's is not a contradiction.

    Without the period on both it looks exactly like one, which is the example
    `docs/auditor-grounding.md` gives by name.
    """
    assert not claim(period="Q3 2026").comparable_to(claim(period="FY2025"))


def test_a_period_is_optional_because_some_figures_have_none():
    """Headcount today has no period, and refusing it would drop a real claim."""
    assert claim(period=None).period is None


def test_a_value_that_is_not_a_number_is_refused():
    """The model returns figures, not prose.

    "1.2M" is the shape a model reaches for and it is not a number. Refused at
    the type rather than parsed, because a parser here is code guessing at
    magnitude — and a magnitude guessed wrong is a claim off by a factor of a
    million, asserted confidently.
    """
    with pytest.raises(ValidationError):
        claim(value="1.2M")


# --- Assertions -----------------------------------------------------------
#
# `Product.md` asks extraction for *"claims, figures, and chart data"* and its
# Auditor for *"contradictions, unsupported claims, and figures that moved"*.
# Claims and figures are distinguished throughout, and most of what is actually
# attackable in a deck is the half that is not a number: exclusivity, a granted
# patent, a competitive absolute, a promise about next quarter.


def test_an_assertion_is_a_claim_without_a_number():
    """The Technical Skeptic's ammunition, and the CFO has none of it.

    A panel that can only challenge figures is a panel of one archetype. This is
    also what `docs/auditor-grounding.md` means by qualitative findings
    *"collected and surfaced in the debrief"* — uncollectable if extraction
    never captured them.
    """
    recorded = assertion()

    assert recorded.kind is ClaimKind.ASSERTION
    assert recorded.subject == "distribution"
    assert recorded.statement.startswith("Exclusive distribution")


def test_an_assertion_carries_a_subject_so_the_right_archetype_can_own_it():
    """§3.3: the domain that owns the figure owns the interruption.

    That rule needs a domain on a non-numeric claim too, or every assertion is
    unroutable and the targeted-interruption promise quietly covers only
    numbers.
    """
    assert assertion(subject="intellectual property").subject == "intellectual property"


def test_an_assertion_is_never_numerically_comparable_to_a_figure():
    """Two kinds, and only one of them supports exact contradiction.

    `docs/auditor-grounding.md` puts the bar for interrupting a live room at a
    contradiction stateable precisely — both figures, both moments. An assertion
    cannot meet that bar, and a `comparable_to` that accepted one would be the
    route by which fuzzy disagreement reaches the live panel.
    """
    assert not hasattr(assertion(), "comparable_to")


def test_a_kind_is_carried_explicitly_rather_than_inferred_from_shape():
    """So storage and routing never guess from which fields happen to be set.

    A discriminator that has to be reconstructed by looking for a null is the
    kind that disagrees with itself once a field becomes optional.
    """
    assert claim().kind is ClaimKind.QUANTITATIVE
    assert assertion().kind is ClaimKind.ASSERTION


def test_an_assertion_without_a_statement_is_refused():
    """An empty assertion is a claim that cites nothing, which is the failure
    mode CLAUDE.md names outright: *"do not ship interrogation logic that can't
    cite its source"*."""
    with pytest.raises(ValidationError):
        assertion(statement="")
