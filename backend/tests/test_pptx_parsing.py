"""A PPTX all the way to pages, which means a real LibreOffice conversion.

The half of PPTX support that needed a binary. `docs/ingestion.md` refused a
hosted conversion API outright — it would ship confidential decks to a third
party, contradicting the retention promise — so the conversion happens in our own
process, and these tests run it for real.

**No stub, deliberately**, for the same reason `storage` is a real MinIO: the
subprocess *is* the risky part. Its failure modes are a hang, a zero exit code on
failure, a profile lock shared between concurrent instances, and a font
substitution that renders a deck subtly wrong. A fake converter would leave every
one of those unexercised until the first deployment.

These need `soffice` on PATH — `brew install --cask libreoffice`, or the package
of the same name. They fail rather than skip when it is missing: a skip is how a
suite reports green while covering nothing.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core.errors import MaterialTooManyPages, MaterialUnreadable
from app.modules.ingestion import parsing
from app.modules.ingestion.parsing import (
    PAGE_MEDIA_TYPE_PDF,
    PPTX_CONTENT_TYPE,
    parse,
)
from tests.pptx import Chart, Table, Text, deck


async def test_a_deck_becomes_pages_a_model_can_look_at():
    """The tracer bullet: a PPTX arrives as rendered pages and a thumbnail.

    The thumbnail is the point of the conversion as much as the pages are. It is
    the one artefact that outlives the deleted source document, and without a
    render there is nothing to make one from — which would mean a placeholder for
    exactly the file type business users bring most.
    """
    parsed = await parse(
        deck(Text("Q3 board review"), Text("Gross margin held at 61%")),
        content_type=PPTX_CONTENT_TYPE,
        max_pages=20,
    )

    assert [page.number for page in parsed.pages] == [1, 2]
    assert all(page.image_media_type == PAGE_MEDIA_TYPE_PDF for page in parsed.pages)
    assert all(Image.open(io.BytesIO(page.image)).width > 0 for page in parsed.pages)
    assert Image.open(io.BytesIO(parsed.thumbnail)).format == "JPEG"


async def test_the_slide_text_survives_the_round_trip_through_pdf():
    """Converted, not retyped — the text layer has to come out the other side.

    LibreOffice writing a PDF with no text layer would still produce pages that
    look right, and the model would fall back to reading pixels. That degrades
    silently, which is why it is asserted rather than assumed.
    """
    parsed = await parse(
        deck(Text("Only vendor with FedRAMP authorization")),
        content_type=PPTX_CONTENT_TYPE,
        max_pages=20,
    )

    assert "FedRAMP" in parsed.pages[0].text


async def test_a_charts_exact_values_are_attached_to_the_slide_it_was_on():
    """Why the file is read twice, in one assertion.

    The render gives a picture of the chart; only the XML gives the numbers. They
    have to arrive on the same page, because a figure is a claim about the slide
    it appeared on — `docs/auditor-grounding.md` cites a locator with every
    claim, and a value attached to the wrong slide is a panelist quoting a page
    the user never wrote.
    """
    parsed = await parse(
        deck(
            Text("Agenda"),
            Chart(
                title="ARR by quarter",
                categories=("Q1", "Q2", "Q3"),
                series={"ARR ($M)": (1.2, 3.45, 7.0)},
            ),
        ),
        content_type=PPTX_CONTENT_TYPE,
        max_pages=20,
    )

    assert parsed.pages[0].charts == ()

    (chart,) = parsed.pages[1].charts
    assert chart.title == "ARR by quarter"
    assert chart.series[0].values == (1.2, 3.45, 7.0)


async def test_a_table_reaches_the_text_layer_one_way_or_another():
    """A table is where a deck puts the numbers it is most confident about."""
    parsed = await parse(
        deck(Table(("Metric", "FY25"), ("Gross margin", "61%"))),
        content_type=PPTX_CONTENT_TYPE,
        max_pages=20,
    )

    assert "Gross margin" in parsed.pages[0].text
    assert "61%" in parsed.pages[0].text


async def test_a_deck_over_the_cap_is_refused_before_anything_is_converted(
    monkeypatch,
):
    """The cap has to bite before the expensive half, or it is not a cap.

    Same rule `_parse_pdf` follows, and it matters more here: converting is a
    subprocess spawning a full office suite, so a cap applied afterwards is a
    bill followed by a refusal. The converter is replaced with something that
    fails loudly, so reaching it cannot be mistaken for passing.
    """

    def refuse(*args, **kwargs):
        raise AssertionError("converted a deck that was over the cap")

    monkeypatch.setattr(parsing, "_convert_to_pdf", refuse)

    with pytest.raises(MaterialTooManyPages) as refused:
        await parse(
            deck(Text("one"), Text("two"), Text("three")),
            content_type=PPTX_CONTENT_TYPE,
            max_pages=2,
        )

    assert refused.value.context["page_count"] == 3


async def test_something_that_is_not_a_deck_is_unreadable_rather_than_a_traceback():
    """Typed, because this runs inside the extraction sweep.

    An unhandled error there marks nothing and leaves the material claimed until
    the requeue notices — so a renamed file has to fail as a material, not as a
    process.
    """
    with pytest.raises(MaterialUnreadable):
        await parse(
            b"%PDF-1.7 not a presentation at all",
            content_type=PPTX_CONTENT_TYPE,
            max_pages=20,
        )


async def test_a_conversion_that_writes_nothing_is_unreadable_despite_exiting_zero(
    monkeypatch,
):
    """`soffice` exits 0 on failures, so the exit code is not the signal.

    Well-known behaviour of the tool, and the reason the output *file* is what
    gets checked. Trusting the return code means a deck that failed to convert
    becomes an empty `ParsedMaterial` — a panel grounded in nothing, reported as
    success, with the source document then deleted as though it had been read.
    """
    import subprocess

    def exits_cleanly_and_writes_nothing(command, **kwargs):
        return subprocess.CompletedProcess(command, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(parsing.subprocess, "run", exits_cleanly_and_writes_nothing)

    with pytest.raises(MaterialUnreadable):
        await parse(
            deck(Text("a perfectly good slide")),
            content_type=PPTX_CONTENT_TYPE,
            max_pages=20,
        )


async def test_two_decks_convert_at_the_same_time_without_deadlocking():
    """LibreOffice serializes on a shared user profile unless told not to.

    The default profile is a lock, so a second instance waits for the first —
    which would turn concurrent extraction into a queue with no error and no
    obvious cause. Each conversion gets its own profile directory; without that,
    this test hangs rather than fails, which is precisely the symptom it exists
    to prevent.
    """
    import asyncio

    decks = [
        parse(
            deck(Text(f"deck {index}")),
            content_type=PPTX_CONTENT_TYPE,
            max_pages=20,
        )
        for index in range(2)
    ]

    parsed = await asyncio.wait_for(asyncio.gather(*decks), timeout=120)

    assert [len(one.pages) for one in parsed] == [1, 1]


def test_a_slide_count_that_disagrees_with_the_page_count_drops_the_structural_half():
    """Hidden slides are the case that breaks matching by position.

    LibreOffice omits a hidden slide from the PDF, so slide three's chart would
    land on page three — which is slide four. A figure that is exactly right and
    cited against a slide the user never showed is the worse failure by a
    distance, and `docs/auditor-grounding.md` says so: a false accusation beats a
    missed catch only in the wrong direction.

    So a mismatch drops the exact values rather than guessing at an alignment.
    Tested directly because producing a hidden slide is a fight with the fixture
    builder, and what is under test is the arithmetic, not PowerPoint.
    """
    pages = (
        parsing.RenderedPage(
            number=1, text="one", image=b"x", image_media_type=PAGE_MEDIA_TYPE_PDF
        ),
        parsing.RenderedPage(
            number=2, text="two", image=b"x", image_media_type=PAGE_MEDIA_TYPE_PDF
        ),
    )
    charted = parsing.SlideChart(
        title="ARR",
        categories=("Q1",),
        series=(parsing.ChartSeries(name="ARR", values=(9.0,)),),
    )
    slides = (
        parsing.SlideContent(number=1, text="one", charts=()),
        parsing.SlideContent(number=2, text="two", charts=()),
        parsing.SlideContent(number=3, text="three", charts=(charted,)),
    )

    merged = parsing._merged(pages, slides)

    assert merged == pages
    assert all(page.charts == () for page in merged)
