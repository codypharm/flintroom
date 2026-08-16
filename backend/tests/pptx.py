"""Build a PPTX, so the parsing tests do not depend on a committed binary.

Same argument as `pdfs.py`: a generator is readable in a diff, needs no build
step, and can produce a deck larger than the page cap without committing one.

**The honest limit of this approach.** These files are written with the same
library that reads them, so a mistake in how `python-pptx` interprets the
DrawingML schema would be invisible here — both halves would be wrong in the same
direction. What it does still prove is the part most likely to break: that we
reach into the right places for text, tables and chart series, and that a chart's
numbers arrive as the exact floats rather than as anything inferred.

The first real PowerPoint file this project gets its hands on — one saved by
PowerPoint itself, with its grouping, its placeholders and its idea of a title —
belongs in `tests/` as a committed fixture beside these.
"""

from __future__ import annotations

from collections.abc import Sequence

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Emu, Inches

#: A 4:3 slide in English Metric Units, which is what PowerPoint stores.
SLIDE_WIDTH = Inches(10)
SLIDE_HEIGHT = Inches(7.5)

#: Index 6 in the default template. Everything here is positioned explicitly, so
#: a layout with no placeholders of its own is the one that gets in the way least.
BLANK_LAYOUT = 6


def _box(left: float = 1, top: float = 1, width: float = 8, height: float = 4):
    return Inches(left), Inches(top), Inches(width), Inches(height)


class Slide:
    """One slide's worth of instructions, applied to a real `pptx` slide."""

    def apply(self, slide) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class Text(Slide):
    """A title line and any number of body lines, in one text box."""

    def __init__(self, *lines: str) -> None:
        self.lines = lines

    def apply(self, slide) -> None:
        box = slide.shapes.add_textbox(*_box())
        frame = box.text_frame
        frame.text = self.lines[0] if self.lines else ""
        for line in self.lines[1:]:
            frame.add_paragraph().text = line


class Table(Slide):
    """A grid of cells — how a deck usually presents the numbers it is proud of."""

    def __init__(self, *rows: Sequence[str]) -> None:
        self.rows = rows

    def apply(self, slide) -> None:
        shape = slide.shapes.add_table(
            len(self.rows), len(self.rows[0]), *_box()
        )
        for row_index, row in enumerate(self.rows):
            for column_index, value in enumerate(row):
                shape.table.cell(row_index, column_index).text = value


class Chart(Slide):
    """A chart, with the values PowerPoint will store in its XML.

    The reason `python-pptx` is a dependency at all: these floats are what the
    author typed, and a vision model reading the same chart is inferring
    magnitudes from bar heights.
    """

    def __init__(
        self,
        *,
        categories: Sequence[str],
        series: dict[str, Sequence[float | None]],
        title: str | None = None,
    ) -> None:
        self.categories = categories
        self.series = series
        self.title = title

    def apply(self, slide) -> None:
        data = CategoryChartData()
        data.categories = list(self.categories)
        for name, values in self.series.items():
            data.add_series(name, list(values))

        graphic = slide.shapes.add_chart(
            XL_CHART_TYPE.COLUMN_CLUSTERED, *_box(), data
        )
        chart = graphic.chart
        chart.has_title = self.title is not None
        if self.title is not None:
            chart.chart_title.text_frame.text = self.title


class Grouped(Slide):
    """Text inside a shape group, which naive iteration walks straight past.

    Not a contrived case: PowerPoint groups shapes whenever somebody selects a
    few and hits ⌘G, and a template's furniture is usually grouped already. A
    reader that only looks at top-level shapes silently loses whatever is inside,
    and the symptom is a deck that grounds nothing with no error anywhere.
    """

    def __init__(self, *lines: str) -> None:
        self.lines = lines

    def apply(self, slide) -> None:
        boxes = []
        for index, line in enumerate(self.lines):
            box = slide.shapes.add_textbox(
                Inches(1), Inches(1 + index * 1.5), Inches(6), Inches(1)
            )
            box.text_frame.text = line
            boxes.append(box)

        group = slide.shapes.add_group_shape(boxes)
        # A group needs its own extents; python-pptx does not infer them.
        group.left, group.top = Inches(1), Inches(1)
        group.width, group.height = Inches(6), Emu(int(Inches(1.5)) * len(boxes))


def deck(*slides: Slide) -> bytes:
    """One slide per instruction, as the bytes a client would upload."""
    from io import BytesIO

    presentation = Presentation()
    presentation.slide_width = SLIDE_WIDTH
    presentation.slide_height = SLIDE_HEIGHT

    for spec in slides:
        spec.apply(presentation.slides.add_slide(
            presentation.slide_layouts[BLANK_LAYOUT]
        ))

    buffer = BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()
