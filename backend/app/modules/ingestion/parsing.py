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

PPTX is not here yet. It converts to PDF through headless LibreOffice and
rejoins this path, and it is separately read with `python-pptx` for exact chart
series — the numbers PowerPoint stored, which beat anything vision infers from
pixels. That lands with its own dependency justification.
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass

import pillow_heif
import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError

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
