"""Build a PDF, so the parsing tests do not depend on a committed binary.

A generator rather than a fixture file for one reason that matters: the page cap
has to be tested against a deck larger than the cap, and committing a
three-hundred-page PDF to prove a twenty-page limit is absurd. Everything else —
being readable in a diff, having no build step, not needing a tool nobody has
installed — follows for free.

Deliberately minimal and uncompressed. What it produces is a real PDF with a real
cross-reference table, because a parser that rebuilds a broken xref would hide
exactly the class of malformed input these tests should be able to construct.
"""

from __future__ import annotations

#: Objects 1 and 2 are the catalogue and the page tree; 3 is the one font. Page
#: objects and their content streams are allocated in pairs from 4 upward.
CATALOG, PAGE_TREE, FONT = 1, 2, 3
FIRST_PAGE_OBJECT = 4


def _escape(text: str) -> str:
    """PDF string literals delimit with parentheses, so those need escaping."""
    for char in ("\\", "(", ")"):
        text = text.replace(char, f"\\{char}")
    return text


def minimal_pdf(*page_texts: str) -> bytes:
    """One page per string, each showing that string in Helvetica.

    US Letter at 72 points to the inch, which is what an unstyled PDF defaults
    to and what the renderer's scaling is therefore exercised against.
    """
    objects: dict[int, bytes] = {
        CATALOG: b"<< /Type /Catalog /Pages 2 0 R >>",
        FONT: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    page_objects: list[int] = []

    for index, text in enumerate(page_texts):
        page_id = FIRST_PAGE_OBJECT + index * 2
        content_id = page_id + 1
        page_objects.append(page_id)

        stream = f"BT /F1 24 Tf 72 700 Td ({_escape(text)}) Tj ET".encode()
        objects[content_id] = (
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
        objects[page_id] = (
            f"<< /Type /Page /Parent {PAGE_TREE} 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {FONT} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode()

    kids = " ".join(f"{page} 0 R" for page in page_objects)
    objects[PAGE_TREE] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_objects)} >>".encode()
    )

    out = bytearray(b"%PDF-1.7\n")
    offsets: dict[int, int] = {}
    for object_id in sorted(objects):
        offsets[object_id] = len(out)
        out += f"{object_id} 0 obj\n".encode() + objects[object_id] + b"\nendobj\n"

    # The cross-reference table: byte offset of every object, in order, so a
    # reader can seek straight to one. Its own offset goes in `startxref`, which
    # is what a reader looks for first.
    xref_offset = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n".encode()
    out += b"0000000000 65535 f \n"
    for object_id in range(1, size):
        out += f"{offsets[object_id]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {size} /Root {CATALOG} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()

    return bytes(out)
