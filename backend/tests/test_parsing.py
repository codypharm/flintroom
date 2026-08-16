"""Bytes to pages. No model, no network, no database.

`docs/ingestion.md` calls this one of the two deep modules in ingestion, and the
reason is visible in the imports: everything below is a function over bytes, so
the part of extraction most likely to be wrong is also the part that needs
nothing to test.

What it has to get right is that a page arrives *twice* — as text and as an
image. Chart values are not in a PDF's text layer, and §3.2 asks for chart data
per slide, so a text-only parser answers half the question and looks like it
answered all of it.
"""

from __future__ import annotations

import asyncio
import io

import pytest
from PIL import Image

from app.core.errors import MaterialTooManyPages, MaterialUnreadable
from app.modules.ingestion.parsing import (
    RENDER_LONG_EDGE,
    THUMBNAIL_LONG_EDGE,
    parse,
)

from tests.pdfs import minimal_pdf

PDF = "application/pdf"


def opened(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def photograph(size: tuple[int, int] = (3024, 4032)) -> bytes:
    """What a phone produces: large, and with no text layer anywhere in it."""
    image = Image.new("RGB", size, (200, 200, 200))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


async def test_a_pdf_becomes_one_page_each_carrying_text_and_a_picture():
    """The tracer bullet, and the whole reason this module renders at all.

    Both halves are asserted together because either alone is a plausible-looking
    parser that loses half the deck: text without an image cannot see a chart's
    values, and an image without text throws away the one exact reading of the
    page we get for free.
    """
    parsed = await parse(
        minimal_pdf("Revenue grew 42 percent", "Margin held at 61 percent"),
        content_type=PDF,
        max_pages=20,
    )

    assert [page.number for page in parsed.pages] == [1, 2]
    assert parsed.pages[0].text == "Revenue grew 42 percent"
    assert parsed.pages[1].text == "Margin held at 61 percent"
    for page in parsed.pages:
        assert opened(page.image).width > 0


async def test_a_page_is_rendered_at_the_size_a_model_stops_gaining_detail_at():
    """Big enough to read a chart axis, and not one pixel bigger.

    Above this a vision model downscales the image itself, so the extra pixels
    are paid for in upload and memory and then discarded. Below it, small figures
    on a dense slide stop being legible — which is the failure that matters here,
    because a misread number put confidently into a panelist's mouth is the one
    thing the grounding story cannot survive.
    """
    parsed = await parse(minimal_pdf("A slide"), content_type=PDF, max_pages=20)

    image = opened(parsed.pages[0].image)

    assert max(image.size) == RENDER_LONG_EDGE


async def test_a_deck_past_the_page_cap_is_refused_before_anything_is_rendered():
    """The ordering is the assertion, and the clock is what proves it.

    Rendering is the expensive half and it is CPU-bound, so a cap applied after
    the work is not a cap — it is a bill followed by a refusal. Two thousand
    pages take about thirty seconds to render on this machine and the refusal
    takes under a millisecond, so the timeout below sits roughly forty times
    under the one and thousands of times over the other. It fails if the check
    ever moves after the loop, and not for any other reason.

    The error carries both numbers because this failure is terminal — no window
    rolls over into a file being shorter, so the user has to send a smaller one,
    and "too long" without a count does not say how much smaller.
    """
    deck = minimal_pdf(*[f"Slide {n}" for n in range(2000)])

    with pytest.raises(MaterialTooManyPages) as refused:
        await asyncio.wait_for(
            parse(deck, content_type=PDF, max_pages=20), timeout=5
        )

    assert refused.value.context["page_count"] == 2000
    assert refused.value.context["max_pages"] == 20


async def test_a_photograph_is_one_page_with_no_text_layer():
    """The mobile-native input in §3.2: a whiteboard, or a slide on a screen.

    An empty string rather than a missing field. There is genuinely no text layer
    in a photograph, and the model reads it from the image — a parser that raised
    here would refuse the input the product most expects from a phone.
    """
    parsed = await parse(photograph(), content_type="image/jpeg", max_pages=20)

    assert len(parsed.pages) == 1
    assert parsed.pages[0].text == ""
    assert max(opened(parsed.pages[0].image).size) == RENDER_LONG_EDGE


async def test_a_heic_photograph_opens():
    """What an iPhone camera produces by default.

    Accepted in `ACCEPTED_CONTENT_TYPES`, so failing to open one would be a
    refusal at the far end of a successful upload — the worst place to discover
    a format is unsupported, because the user already waited for it.
    """
    import pillow_heif

    buffer = io.BytesIO()
    Image.new("RGB", (2000, 1500), (180, 180, 180)).save(buffer, format="HEIF")
    pillow_heif.register_heif_opener()

    parsed = await parse(buffer.getvalue(), content_type="image/heic", max_pages=20)

    assert len(parsed.pages) == 1


async def test_a_photograph_is_turned_the_right_way_up():
    """Phones record orientation in EXIF rather than rotating the pixels.

    A whiteboard photographed in portrait arrives as a landscape image with a
    note saying which way is up, and a parser that ignores the note hands the
    model a sideways slide. That reads as a bad model rather than as a bug.
    """
    portrait = Image.new("RGB", (400, 800), (200, 200, 200))
    buffer = io.BytesIO()
    # Orientation 6: stored rotated 90° clockwise from how it should display.
    exif = portrait.getexif()
    exif[274] = 6
    portrait.save(buffer, format="JPEG", exif=exif)

    parsed = await parse(buffer.getvalue(), content_type="image/jpeg", max_pages=20)

    image = opened(parsed.pages[0].image)
    assert image.width > image.height


async def test_the_camera_metadata_does_not_survive_the_parser():
    """A photo of a whiteboard carries where it was taken.

    CLAUDE.md starts every feature with privacy, and this is the version of it
    that is easy to miss: nobody uploaded their location, and the page image
    outlives the source document. Orientation is read and applied first, so
    dropping the rest costs nothing.
    """
    original = Image.new("RGB", (800, 600), (200, 200, 200))
    buffer = io.BytesIO()
    exif = original.getexif()
    exif[271] = "SomePhoneMaker"  # Make
    exif[306] = "2026:08:16 09:00:00"  # DateTime
    original.save(buffer, format="JPEG", exif=exif)

    parsed = await parse(buffer.getvalue(), content_type="image/jpeg", max_pages=20)

    assert not dict(opened(parsed.pages[0].image).getexif())


async def test_the_thumbnail_is_page_one_and_small_enough_to_keep_forever():
    """The one artefact that outlives the deleted source document.

    Small because it is kept indefinitely and shown in a list. It inherits the
    claims' retention rules exactly and is never weaker — a title slide routinely
    carries the company name, the round size and the word "Confidential".
    """
    parsed = await parse(
        minimal_pdf("Q3 Board Deck", "Appendix"), content_type=PDF, max_pages=20
    )

    assert max(opened(parsed.thumbnail).size) == THUMBNAIL_LONG_EDGE
    assert len(parsed.thumbnail) < 60 * 1024


async def test_a_file_that_is_not_what_it_claimed_fails_typed():
    """The declared content type is a claim until something reads the bytes.

    The presign binds the type the *client* sent to the type we recorded, which
    is not the same as the file being that type. This is where the difference
    surfaces, and it has to be a typed failure: an unhandled exception here runs
    inside the extraction sweep, where it would mark nothing, log a traceback,
    and leave the material claimed until the requeue notices.
    """
    with pytest.raises(MaterialUnreadable):
        await parse(b"MZ\x90\x00 not a deck", content_type=PDF, max_pages=20)


async def test_a_type_the_parser_has_no_path_for_fails_typed():
    """Belt and braces against `ACCEPTED_CONTENT_TYPES` and this module drifting.

    They are two lists that have to agree, and the moment one gains an entry the
    other lacks, an upload succeeds and extraction dies. Typed, so that failure
    is a material marked `failed` rather than a traceback in a sweep.
    """
    with pytest.raises(MaterialUnreadable):
        await parse(b"anything", content_type="text/csv", max_pages=20)
