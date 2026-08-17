"""The Auditor catching a user contradicting themselves.

`docs/auditor-grounding.md` reframes the Auditor as two jobs that had been
collapsed into one word. *Grounding* — a challenge tracing to something specific
— needs only that the user said something, and they are speaking claims
continuously. *Cross-checking* needs a reference, and that is what a deckless
session lacks.

The answer is that **the transcript is the reference**: a running set of figures
the user has stated, checked against each new one. It is also what actually
happens in the format that prompted the question — the sharks have no deck, and
they catch people because the numbers fail against *each other*.

No model here. `docs/auditor-grounding.md` makes the extract/compute split
structural rather than stylistic: the model's only job is pulling figures out of
speech into a typed claim, and every comparison is ordinary code. If the
comparison needed a model to test, the split has leaked.
"""

from __future__ import annotations

from app.agents.auditor import Auditor, SpokenClaim
from app.modules.ingestion.schemas import QuantitativeClaim, Unit


def said(
    metric: str,
    value: float,
    *,
    at: int,
    unit: Unit = Unit.PERCENT,
    period: str | None = "Q3 2026",
    quote: str = "spoken",
) -> SpokenClaim:
    return SpokenClaim(
        claim=QuantitativeClaim(
            quote=quote, metric=metric, value=value, unit=unit, period=period
        ),
        at_seconds=at,
    )


def test_a_figure_that_moved_is_caught_with_both_numbers_and_both_moments():
    """The tracer bullet, and the bar the doc sets for interrupting a live room.

    *"A contradiction the Auditor can state precisely: both figures, both
    moments."* Anything vaguer is a panel asserting that something is wrong
    without being able to say what, which is worse than saying nothing — it
    hands the user a reason to dismiss everything else in the session.

    Both moments matter as much as both figures. "You said sixty-one and then
    seventy" is an accusation; "at two minutes you said sixty-one, at nine you
    said seventy" is evidence, and the difference is whether the user can check
    it.
    """
    auditor = Auditor()

    assert auditor.hear(said("gross margin", 61, at=120)) is None
    caught = auditor.hear(said("gross margin", 70, at=540))

    assert caught is not None
    assert "61" in caught.summary and "70" in caught.summary
    assert "2:00" in caught.summary and "9:00" in caught.summary


def test_a_person_rounding_their_own_number_is_not_contradicting_themselves():
    """*"A false accusation is worse than a missed catch."*

    The doc's own example: *"About forty then thirty-eight is not a
    contradiction, it is a person talking."* Nobody speaks to two decimal
    places, and a panel that pounces on rounding is not intimidating — it is
    stupid, and it hands the user a reason to dismiss everything else it says.

    This is the test that matters more than the true positive above. A missed
    catch costs one challenge; a false one costs the room its credibility, and
    credibility is the entire product.
    """
    auditor = Auditor()

    auditor.hear(said("gross margin", 40, at=60))

    assert auditor.hear(said("gross margin", 38, at=300)) is None


def test_the_same_disagreement_is_judged_the_same_whichever_way_it_ran():
    """A figure revised down must be treated exactly as one revised up.

    The gap between 92 and 100 is one disagreement, and which number was said
    first is a fact about the conversation rather than about the arithmetic.
    Measured against the earlier figure it is 8% going down and 8.7% going up,
    so a threshold between them catches a user who revises downward and forgives
    the identical revision upward — a room that is harsher on people admitting a
    number was worse than they said, which is precisely backwards.

    Written after the mutation survived. The reasoning was in the docstring and
    nothing held it there.
    """
    falling, rising = Auditor(), Auditor()

    falling.hear(said("headcount", 100, at=60, unit=Unit.COUNT))
    rising.hear(said("headcount", 92, at=60, unit=Unit.COUNT))

    fell = falling.hear(said("headcount", 92, at=300, unit=Unit.COUNT))
    rose = rising.hear(said("headcount", 100, at=300, unit=Unit.COUNT))

    assert (fell is None) == (rose is None)


def test_two_figures_about_different_periods_never_disagree():
    """*"Last quarter's revenue against last year's is not a contradiction."*

    The doc names comparability as the source of most false positives, and this
    is the sharpest case: the two numbers *should* differ, and a room that
    challenges somebody for growing is a room that has not understood the
    sentence.

    `QuantitativeClaim.comparable_to` already enforces it, and this asserts it
    from the Auditor's side anyway. The guard lives in a type this module does
    not own, and a well-meant relaxation of it there would silently turn every
    growing metric in every session into an accusation — with nothing in
    ingestion's own tests to object, because ingestion never compares two
    spoken figures.
    """
    auditor = Auditor()

    auditor.hear(said("revenue", 400_000, at=60, unit=Unit.USD, period="Q1 2026"))
    later = auditor.hear(
        said("revenue", 900_000, at=300, unit=Unit.USD, period="Q3 2026")
    )

    assert later is None


def test_a_figure_restated_unchanged_is_somebody_being_consistent():
    """The commonest thing in a rehearsal, and it must be silent.

    People repeat their headline number — it is the one they have practised.
    Every repetition is a chance for the Auditor to fire, so a room that treats
    restatement as contradiction gets louder the more consistent the user is,
    which inverts the entire signal.
    """
    auditor = Auditor()

    auditor.hear(said("ARR", 1_200_000, at=45, unit=Unit.USD))

    assert auditor.hear(said("ARR", 1_200_000, at=400, unit=Unit.USD)) is None
