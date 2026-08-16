"""Turning a stored claim into something a panelist can quote back.

`Grounding.claims` is documented as *"pre-rendered as citable lines"* rather than
as ingestion's typed `ExtractedClaim`, which keeps the panel free of the
ingestion module and the seam one-directional: whoever owns a claim owns how it
reads. This is that rendering, and it lives in ingestion for exactly that reason.

It is also the last hop in the requirement `CLAUDE.md` states most bluntly —
*"do not ship interrogation logic that can't cite its source"*. A panelist handed
a bare figure can only ask a hard-sounding question about a number; one handed
the sentence the deck actually wrote can read it back.
"""

from __future__ import annotations

from app.modules.ingestion.citations import citable
from app.modules.ingestion.extraction_model import ExtractedClaim
from app.modules.ingestion.schemas import AssertionClaim, QuantitativeClaim, Unit


def test_a_figure_reads_back_as_the_sentence_the_deck_wrote():
    """The quote, not a reconstruction of it.

    Rebuilding a line from `metric`, `value` and `unit` would produce "gross
    margin of 61.0%" — accurate, and not what is on the slide. The whole value
    of a grounded challenge is that the user recognises their own sentence
    coming back at them, and a paraphrase forfeits that while sounding almost
    right.
    """
    line = citable(
        ExtractedClaim(
            page=4,
            claim=QuantitativeClaim(
                quote="Gross margin held at 61% in Q3.",
                metric="gross margin",
                value=61.0,
                unit=Unit.PERCENT,
                period="Q3 2026",
            ),
            quote_verified=True,
        )
    )

    assert line == "Gross margin held at 61% in Q3. (slide 4)"


def test_a_figure_read_off_a_chart_says_so():
    """A quote that lives in pixels must not be presented as deck text.

    `quote_verified` is False for a figure a vision model read off a chart: it
    appears in no text layer, which is the whole reason a vision model is in the
    pipeline. Its own documentation says the panel *"should be able to tell
    which of its ammunition is confirmed verbatim before deciding what to press
    hardest on"*, and this is where that becomes true.

    The stakes are `docs/auditor-grounding.md`'s rule that *"a false accusation
    is worse than a missed catch"*. A panelist saying "your slide says 61%" when
    those words were never written is exactly that — and it is the kind of
    mistake a user can disprove instantly, in the one product whose credibility
    is its whole value.
    """
    line = citable(
        ExtractedClaim(
            page=7,
            claim=QuantitativeClaim(
                quote="ARR reaches $4.2M by Q4.",
                metric="ARR",
                value=4_200_000.0,
                unit=Unit.USD,
                period="Q4 2026",
            ),
            quote_verified=False,
        )
    )

    assert line == "ARR reaches $4.2M by Q4. (slide 7, read from a chart)"


def test_an_assertion_reads_back_the_same_way_a_figure_does():
    """Both kinds render through `quote`, and the caller never branches.

    An assertion is most of what is genuinely attackable in a deck — exclusivity,
    a patent, a promise about next quarter — and it reaches the panel as the same
    kind of line a figure does. A renderer that treated them differently would
    push the union back out into whoever assembles `Grounding`, which is the
    coupling this module exists to prevent.
    """
    line = citable(
        ExtractedClaim(
            page=2,
            claim=AssertionClaim(
                quote="We are the only vendor with a granted patent here.",
                subject="intellectual property",
                statement="Sole patent holder in the category.",
            ),
            quote_verified=True,
        )
    )

    assert line == "We are the only vendor with a granted patent here. (slide 2)"
