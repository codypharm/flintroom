"""Reading a PPTX for what PowerPoint actually stored.

The half of PPTX support that is not a render, and the half that carries the
numbers. `docs/ingestion.md`: a chart authored in PowerPoint keeps its values in
the XML, and *"those exact values beat anything vision infers from pixels, and
win on conflict"* — because a misread figure put confidently into a panelist's
mouth is the one failure `docs/auditor-grounding.md` says the grounding story
cannot survive.

So the bar here is not "did we get some text out". It is that a number the author
typed arrives as that number, attached to the slide it was on and the thing it
was measuring.
"""

from __future__ import annotations

import pytest

from app.core.errors import MaterialUnreadable
from app.modules.ingestion.parsing import pptx_slides
from tests.pptx import Chart, Grouped, Table, Text, deck


def test_a_chart_gives_up_the_numbers_the_author_typed():
    """The reason this dependency exists at all.

    Asserted as exact floats rather than approximately, because approximate is
    what the vision path already offers. If these came back rounded or reordered
    there would be no point reading the file structurally — the model would be
    the better source, and it is not.
    """
    slides = pptx_slides(
        deck(
            Chart(
                title="Revenue by quarter",
                categories=("Q1", "Q2", "Q3"),
                series={"ARR ($M)": (1.2, 3.45, 7.0)},
            )
        )
    )

    (chart,) = slides[0].charts
    assert chart.title == "Revenue by quarter"
    assert chart.categories == ("Q1", "Q2", "Q3")

    (series,) = chart.series
    assert series.name == "ARR ($M)"
    assert series.values == (1.2, 3.45, 7.0)


def test_several_series_stay_separate_and_keep_their_names():
    """Two lines on one chart are two different claims.

    Flattening them would produce a figure attached to no metric, which is worse
    than not reading the chart: the Auditor compares *metric plus period*, and a
    value with the wrong metric is how a false accusation gets made.
    """
    slides = pptx_slides(
        deck(
            Chart(
                categories=("2025", "2026"),
                series={"Revenue": (10.0, 22.0), "Cost": (8.0, 12.0)},
            )
        )
    )

    (chart,) = slides[0].charts
    assert {series.name: series.values for series in chart.series} == {
        "Revenue": (10.0, 22.0),
        "Cost": (8.0, 12.0),
    }


def test_a_gap_in_a_chart_stays_a_gap_and_stays_in_place():
    """The case that decides whether a figure is attached to the right period.

    A chart with no value for Q2 has two tempting wrong answers. Zero says the
    quarter made nothing, which the deck never claimed. Dropping it shifts every
    later value onto the wrong category, so Q3's revenue reads as Q2's — a number
    that is exactly right and attached to the wrong period, which is precisely
    how a false accusation gets made out of correct data.

    `docs/auditor-grounding.md` refuses to compare two figures without matching
    periods, so alignment with `categories` is the whole contract.
    """
    slides = pptx_slides(
        deck(
            Chart(
                categories=("Q1", "Q2", "Q3"),
                series={"Revenue": (5.0, None, 9.0)},
            )
        )
    )

    (chart,) = slides[0].charts
    (series,) = chart.series
    assert series.values == (5.0, None, 9.0)
    assert len(series.values) == len(chart.categories)


def test_a_chart_with_no_title_is_read_anyway():
    """Most charts in a real deck have no title — the slide's heading is the title.

    Worth a test because `has_title` is false by default and reaching for the
    title regardless raises, which would fail the whole deck over the ordinary
    case rather than the exotic one.
    """
    slides = pptx_slides(
        deck(Chart(categories=("A",), series={"Users": (400.0,)}))
    )

    (chart,) = slides[0].charts
    assert chart.title == ""
    assert chart.series[0].values == (400.0,)


def test_the_text_on_a_slide_comes_back_in_reading_order():
    """The claims that are sentences rather than figures.

    `docs/ingestion.md` wants assertions as well as numbers — exclusivity, a
    granted patent, a competitive absolute — and those are prose on a slide.
    """
    slides = pptx_slides(
        deck(Text("Why we win", "Only vendor with FedRAMP", "Two-year head start"))
    )

    assert "Why we win" in slides[0].text
    assert "Only vendor with FedRAMP" in slides[0].text
    assert "Two-year head start" in slides[0].text


def test_a_table_is_text_and_not_silently_dropped():
    """A table is where a deck puts the numbers it is most confident about.

    Table cells are not text frames on the shape, so a reader that only asks for
    `has_text_frame` returns an empty slide for the densest page in the deck —
    with no error, which is the failure this codebase keeps refusing to ship.
    """
    slides = pptx_slides(
        deck(Table(("Metric", "FY25"), ("Gross margin", "61%")))
    )

    text = slides[0].text
    assert "Gross margin" in text
    assert "61%" in text


def test_text_inside_a_group_is_not_lost():
    """PowerPoint groups shapes whenever anybody selects a few and hits ⌘G.

    Naive iteration walks past a group's children, so a template whose furniture
    is grouped — which is most of them — grounds nothing and says nothing about
    why.
    """
    slides = pptx_slides(deck(Grouped("Series B", "$40M at $300M pre")))

    assert "Series B" in slides[0].text
    assert "$40M at $300M pre" in slides[0].text


def test_slides_keep_their_order_and_number_from_one():
    """The locator every claim is cited by.

    1-based because it is shown to a user and quoted back at them by a panelist:
    *"on slide four you said"*. Off by one here is a panelist citing the wrong
    slide, which reads as the panel being wrong about everything.
    """
    slides = pptx_slides(deck(Text("first"), Text("second"), Text("third")))

    assert [slide.number for slide in slides] == [1, 2, 3]
    assert [slide.text.strip() for slide in slides] == ["first", "second", "third"]


def test_something_that_is_not_a_pptx_is_refused_as_unreadable():
    """Typed, because this runs inside the extraction sweep.

    An unhandled exception there marks nothing and leaves the material claimed
    until the requeue notices — the same reasoning `_parse_pdf` gives for
    catching `PdfiumError`.
    """
    with pytest.raises(MaterialUnreadable):
        pptx_slides(b"%PDF-1.7 this is not a presentation")
