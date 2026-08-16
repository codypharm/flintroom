"""How a claim reads when the panel quotes it back.

`Grounding.claims` takes pre-rendered lines rather than typed claims, which
keeps the panel free of this module and the seam one-directional — whoever owns
a claim owns how it reads. So the rendering lives here, with the claim, and the
panel never learns that `QuantitativeClaim` exists.

This is the last hop in the requirement `CLAUDE.md` states most bluntly: *"do not
ship interrogation logic that can't cite its source."* Open Risk #2 is that
ungrounded generic questions kill retention faster than any UI flaw, and a
panelist handed a bare figure can only produce a hard-sounding question about a
number it has never seen in context.
"""

from __future__ import annotations

from app.modules.ingestion.extraction_model import ExtractedClaim
from app.modules.ingestion.models import MaterialClaim


def citable(claim: ExtractedClaim) -> str:
    """One claim, as a line a panelist can read back and a user will recognise.

    The stored `quote` verbatim, never a reconstruction from the parsed fields.
    Rebuilding a quantitative claim from `metric`, `value` and `unit` yields
    "gross margin of 61.0%" — accurate, and not what is on the slide. The entire
    force of a grounded challenge is the user hearing their own sentence come
    back at them, and a paraphrase forfeits that while sounding almost right.

    The slide number rides along because §3.3's targeted interruption is only
    intimidating if it can say *where*. "Your own slide 4 says" is a different
    experience from "you said somewhere".

    An unverified quote is marked as read from a chart, and that marking is a
    correctness guard rather than a nicety. Those figures live in pixels and
    appear in no text layer — a panelist asserting "your slide *says* 61%" when
    those words were never written is the false accusation
    `docs/auditor-grounding.md` rates as worse than a missed catch, and it is
    the kind a user can disprove in one second by looking at their own deck.
    """
    if claim.quote_verified:
        return f"{claim.claim.quote} (slide {claim.page})"
    return f"{claim.claim.quote} (slide {claim.page}, read from a chart)"


def citable_row(row: MaterialClaim) -> str:
    """One stored claim, as a citable line.

    Exists so that a caller outside this module never has to reach for
    `service._extracted_claim` to get from a row to a line. Reconstructing the
    typed claim is ingestion's business — the discriminated union, the unit
    vocabulary and the comparability rules are all here — and a voice module
    importing a private function to do it would couple to exactly the internals
    the pre-rendered-lines contract exists to hide.
    """
    from app.modules.ingestion.service import _extracted_claim

    return citable(_extracted_claim(row))
