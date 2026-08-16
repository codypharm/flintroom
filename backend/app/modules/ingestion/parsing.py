"""Bytes to pages, with no model in the loop.

One of the two deep modules in ingestion (`docs/ingestion.md`): a pure function
over bytes, so the part of extraction most likely to be wrong is also the part
that needs no model, no network and no database to test.

**A page is produced twice, as text and as an image, and both are needed.**
`Product.md` §3.2 asks for claims, figures *and chart data* per slide, and chart
values are not in a PDF's text layer — a text extractor returns a chart's axis
labels and none of its numbers. The text is the one exact reading of the page we
get for free, and the image is the only way to see everything else.

Everything here runs off the event loop. Rasterization is CPU-bound and will
block it, which degrades API latency for every concurrent request in the same
process — so `parse` is the only public entry point and it is a coroutine that
does its work in a thread. Exposing the synchronous half would make forgetting
that a one-line mistake with no visible symptom until the box is busy.

**PPTX is half here.** `pptx_slides` reads the file structurally — text, tables,
and the exact chart values PowerPoint stored, which beat anything vision infers
from bar heights. The other half converts the file to PDF through headless
LibreOffice so it rejoins `_parse_pdf`, and that half is not built: without it
there is no PPTX thumbnail and a chart pasted in as an image has no XML for
anyone to read. Until both halves are here `_parse` has no PPTX branch, so a
PPTX reaching it is still failed as unreadable — and it can reach it, because
`ACCEPTED_CONTENT_TYPES` has always accepted the type. That gap is older than
this module and is closed by the render, not by this half.
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from zipfile import BadZipFile

import pillow_heif
import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.exc import PackageNotFoundError

from app.core.errors import MaterialTooManyPages, MaterialUnreadable
from app.core.logging import get_logger

log = get_logger(__name__, tag="ingestion")

# Registers HEIC/HEIF with Pillow. An import for its side effect, which is the
# library's documented interface — an iPhone's default photo format is otherwise
# accepted at upload and unopenable afterwards.
pillow_heif.register_heif_opener()

#: Longest edge of a rendered page, in pixels.
#:
#: The size a vision model stops gaining detail at. Larger and the model
#: downscales it anyway, so the extra pixels are paid for in memory and upload
#: and then discarded; smaller and a dense slide's small figures stop being
#: legible — which is the failure that matters, because a misread number put
#: confidently into a panelist's mouth is the one thing the grounding story
#: cannot survive.
RENDER_LONG_EDGE = 1568

#: Longest edge of the thumbnail, in pixels.
#:
#: The only artefact that outlives the deleted source document, so it is sized
#: for a list row and nothing more. It inherits the claims' retention rules
#: exactly and is never weaker: a title slide routinely carries the company
#: name, the round size and the word "Confidential".
THUMBNAIL_LONG_EDGE = 512

#: Rendered pages are PNG and photographs are JPEG, which is not an
#: inconsistency — it is the format each is smaller in. A rendered slide is flat
#: colour and sharp type, where PNG compresses well and JPEG puts ringing
#: artefacts around exactly the small digits we are trying to read. A photograph
#: is sensor noise, where PNG is enormous and lossless-ness buys nothing.
PAGE_MEDIA_TYPE_PDF = "image/png"
PAGE_MEDIA_TYPE_PHOTO = "image/jpeg"
THUMBNAIL_MEDIA_TYPE = "image/jpeg"

_THUMBNAIL_QUALITY = 75
_PHOTO_QUALITY = 88

#: What this module has a path for. Narrower than `ACCEPTED_CONTENT_TYPES` while
#: PPTX is outstanding, and checked rather than assumed — the two lists have to
#: agree, and the moment one gains an entry the other lacks, an upload succeeds
#: and extraction dies.
PDF_CONTENT_TYPE = "application/pdf"
PPTX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)
IMAGE_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/heic", "image/heif"}
)


@dataclass(frozen=True)
class RenderedPage:
    """One page, read both ways."""

    #: 1-based, because it is shown to a user and cited in a claim's locator.
    number: int

    #: The text layer, or empty for a photograph. Empty rather than absent: a
    #: photograph genuinely has none, and the model reads it from the image.
    text: str

    image: bytes
    image_media_type: str


@dataclass(frozen=True)
class ChartSeries:
    """One series of a chart, as the numbers the author typed.

    `python-pptx` documents `Series.values` as *"a sequence containing the float
    values for this series, in the order they appear on the chart"* — so this is
    not an interpretation of the chart, it is the data behind it.
    """

    #: What the series is measuring. Empty when the author never named it, which
    #: is common on a single-series chart where the slide's heading says it.
    name: str

    #: One value per category, `None` where the chart has a gap.
    #:
    #: The gap is kept rather than dropped or zeroed, and both alternatives are
    #: worse in the same way. Zero says the quarter made nothing. Dropping it
    #: shifts every later value onto the wrong category, so a missing Q2 makes
    #: Q3's revenue read as Q2's — a figure that is exactly right and attached to
    #: the wrong period, which is how a false accusation is made from correct
    #: data. Positional alignment with `SlideChart.categories` is the whole
    #: contract here.
    values: tuple[float | None, ...]


@dataclass(frozen=True)
class SlideChart:
    """A chart, without its picture.

    Kept apart from the slide's text rather than flattened into it, because the
    two have different standing: text is something a model has to interpret, and
    these numbers are already exact. Merging them would lose the distinction that
    makes them worth reading separately.
    """

    #: Empty when the chart has no title of its own.
    title: str

    #: The x-axis labels, which are usually the period a figure covers — and
    #: `docs/auditor-grounding.md` will not compare two figures without one.
    categories: tuple[str, ...]

    series: tuple[ChartSeries, ...]


@dataclass(frozen=True)
class SlideContent:
    """One slide, read structurally rather than rasterized."""

    #: 1-based, matching `RenderedPage.number`, because a claim's locator is
    #: quoted back at the user by a panelist: *"on slide four you said"*.
    number: int

    text: str

    charts: tuple[SlideChart, ...]


@dataclass(frozen=True)
class ParsedMaterial:
    """Everything a deck becomes before a model sees it."""

    pages: tuple[RenderedPage, ...]

    #: A downscale of page one, in `THUMBNAIL_MEDIA_TYPE`.
    thumbnail: bytes


async def parse(
    data: bytes, *, content_type: str, max_pages: int
) -> ParsedMaterial:
    """Read a material into pages, off the event loop.

    `max_pages` is the caller's tier cap and is checked against the page count
    before anything is rendered. Rendering is the expensive half, so a cap
    applied afterwards is not a cap — it is a bill followed by a refusal.
    """
    return await asyncio.to_thread(
        _parse, data, content_type=content_type, max_pages=max_pages
    )


def _parse(data: bytes, *, content_type: str, max_pages: int) -> ParsedMaterial:
    if content_type == PDF_CONTENT_TYPE:
        return _parse_pdf(data, max_pages=max_pages)
    if content_type in IMAGE_CONTENT_TYPES:
        return _parse_photograph(data)

    # Not a client error at this point — the type was validated before the
    # presign, so arriving here means this module and `ACCEPTED_CONTENT_TYPES`
    # have drifted apart. Typed anyway, so the drift is a material marked
    # `failed` rather than a traceback inside a sweep.
    log.error("material_type_has_no_parser", content_type=content_type)
    raise MaterialUnreadable(content_type=content_type)


def _parse_pdf(data: bytes, *, max_pages: int) -> ParsedMaterial:
    try:
        document = pdfium.PdfDocument(data)
        page_count = len(document)
    except pdfium.PdfiumError as exc:
        # The declared type is a claim the presign made binding on the client,
        # not one that makes the bytes a PDF. Password-protected decks land here
        # too, which is why the message mentions both.
        log.warning("material_unreadable", content_type=PDF_CONTENT_TYPE)
        raise MaterialUnreadable() from exc

    if page_count > max_pages:
        raise MaterialTooManyPages(page_count=page_count, max_pages=max_pages)

    pages = tuple(
        RenderedPage(
            number=index + 1,
            text=page.get_textpage().get_text_bounded(),
            image=_encode_png(_render(page)),
            image_media_type=PAGE_MEDIA_TYPE_PDF,
        )
        for index, page in enumerate(document)
    )

    return ParsedMaterial(
        pages=pages, thumbnail=_thumbnail(_render(document[0]))
    )


def _parse_photograph(data: bytes) -> ParsedMaterial:
    """One page, no text layer. The whiteboard case in §3.2."""
    try:
        image = Image.open(io.BytesIO(data))
        # Applied before anything else reads the pixels. Phones record which way
        # is up in EXIF rather than rotating the sensor data, so a portrait
        # whiteboard arrives as a landscape image with a note attached — and a
        # parser that ignores the note hands the model a sideways slide, which
        # reads as a bad model rather than as a bug.
        image = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        log.warning("material_unreadable")
        raise MaterialUnreadable() from exc

    return ParsedMaterial(
        pages=(
            RenderedPage(
                number=1,
                text="",
                image=_encode_jpeg(_fit(image, RENDER_LONG_EDGE), _PHOTO_QUALITY),
                image_media_type=PAGE_MEDIA_TYPE_PHOTO,
            ),
        ),
        thumbnail=_thumbnail(image),
    )


def pptx_slides(data: bytes) -> tuple[SlideContent, ...]:
    """Read a PPTX for what PowerPoint stored, without rendering anything.

    The structural half of PPTX support. The other half converts the file to PDF
    and rejoins `_parse_pdf`, because a pasted chart *image* has no XML and only
    vision reads that — but where the author typed a number, this is where the
    number is, and `docs/ingestion.md` says those values win on conflict.

    Synchronous, like everything else here, and called from `parse`'s thread. It
    is XML rather than rasterization so it is cheap, but "cheap" on a
    three-hundred-slide deck is still not something to do on the event loop.
    """
    try:
        presentation = Presentation(io.BytesIO(data))
        slides = list(presentation.slides)
    except (PackageNotFoundError, BadZipFile, KeyError) as exc:
        # A PPTX is a zip of XML, and it fails in three shapes: no such package,
        # bytes that are not an archive at all, and a perfectly good archive
        # whose parts are not where the schema says (a KeyError from the part
        # lookup — a .docx renamed to .pptx lands here). All three are the same
        # fact, which is that the declared type was a claim and the bytes
        # disagree.
        #
        # Typed rather than allowed to escape, for the reason `_parse_pdf` gives:
        # this runs inside the sweep, where an unhandled error marks nothing and
        # leaves the material claimed until the requeue notices.
        log.warning("material_unreadable", content_type=PPTX_CONTENT_TYPE)
        raise MaterialUnreadable() from exc

    return tuple(
        SlideContent(
            number=index + 1,
            text="\n".join(_shape_text(_flatten(slide.shapes))),
            charts=tuple(_charts(_flatten(slide.shapes))),
        )
        for index, slide in enumerate(slides)
    )


def _flatten(shapes) -> list:
    """Every shape on a slide, including the ones inside groups.

    PowerPoint groups shapes whenever somebody selects a few and presses ⌘G, and
    a template's furniture usually arrives grouped already. Iterating only the
    top level silently returns an empty slide for a deck that is full of text —
    no error, nothing in a log, just a deck that grounds nothing.
    """
    found = []
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            found.extend(_flatten(shape.shapes))
        else:
            found.append(shape)
    return found


def _shape_text(shapes) -> list[str]:
    """Text from anything on the slide that holds any.

    Tables are read cell by cell rather than skipped. A table is where a deck
    puts the numbers it is most confident about, and cells are not text frames
    on the shape — so asking only for `has_text_frame` returns nothing for the
    densest page in the file.
    """
    lines = []
    for shape in shapes:
        if shape.has_text_frame and shape.text_frame.text.strip():
            lines.append(shape.text_frame.text)
        if getattr(shape, "has_table", False):
            for row in shape.table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                lines.append("\t".join(cells))
    return lines


def _charts(shapes) -> list[SlideChart]:
    """Every chart on the slide, as the values behind it rather than its picture."""
    charts = []
    for shape in shapes:
        if not getattr(shape, "has_chart", False):
            continue
        chart = shape.chart
        charts.append(
            SlideChart(
                # `chart_title` raises when there is none, and most charts in a
                # real deck have none — the slide's heading is doing that job.
                title=chart.chart_title.text_frame.text if chart.has_title else "",
                categories=tuple(str(category) for category in chart.plots[0].categories),
                series=tuple(
                    ChartSeries(
                        name=series.name or "",
                        # Positional, gaps included. See `ChartSeries.values`:
                        # the index into `categories` is what makes a number a
                        # claim about a period, so nothing may shift.
                        values=tuple(
                            None if value is None else float(value)
                            for value in series.values
                        ),
                    )
                    for series in chart.series
                ),
            )
        )
    return charts


def _render(page: pdfium.PdfPage) -> Image.Image:
    """Rasterize one page at `RENDER_LONG_EDGE`.

    The scale is derived from the page's own dimensions rather than fixed, so an
    A0 poster and a phone-sized slide both arrive at a size the model reads the
    same way. Clamped above so a pathologically small page cannot ask for a
    gigapixel render out of a few hundred bytes of input.
    """
    width, height = page.get_size()
    scale = min(RENDER_LONG_EDGE / max(width, height), 4.0)
    return page.render(scale=scale).to_pil().convert("RGB")


def _fit(image: Image.Image, long_edge: int) -> Image.Image:
    """Scale to fit a box, preserving aspect ratio, up or down."""
    scale = long_edge / max(image.size)
    size = (max(round(image.width * scale), 1), max(round(image.height * scale), 1))
    return image.resize(size, Image.Resampling.LANCZOS)


def _thumbnail(page: Image.Image) -> bytes:
    return _encode_jpeg(_fit(page, THUMBNAIL_LONG_EDGE), _THUMBNAIL_QUALITY)


def _encode_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    """Encode without carrying anything the camera attached.

    Pillow writes no EXIF unless handed some, and none is handed over here on
    purpose: orientation has already been applied, and everything else in that
    block is metadata nobody uploaded — a photograph of a whiteboard records
    where it was taken, and the page image outlives the source document.
    """
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()
