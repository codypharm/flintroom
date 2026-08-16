"""The seam an extraction model plugs into.

Structural (`Protocol`) rather than inherited, like `voice.provider` and
`core.storage`: an adapter is a class that happens to fit rather than one that
had to import us, so a vendor SDK wrapper never acquires a dependency on our
module graph.

**Chosen independently of the panel LLM**, and `docs/ingestion.md` gives the
reason: the two jobs have opposite requirements. Extraction is batch,
latency-insensitive, structured-output and run once per deck; the panel is
conversational and dies above ~1.5s. Coupling them would make ingestion inherit
Phase 3's blockage and buy nothing.

**The interface takes rendered pages, not a PDF.** A model without native
document input must still be usable, and an interface promising what only some
vendors can honour turns a configuration error into a runtime failure.

> **Naming.** `docs/ingestion.md` sketches this as `model.py` plus a `models/`
> package, which Python cannot have alongside the `models.py` that already holds
> the ORM. Named for the voice module's `provider.py` / `providers/` pairing
> instead — same shape, no collision.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ingestion.parsing import RenderedPage
from app.modules.ingestion.schemas import Claim


class ExtractedClaim(BaseModel):
    """A claim, and the page it was found on.

    The locator sits here rather than on the claim itself because the Auditor
    compares a slide's figure against a spoken one, and those two have different
    locators — a page here, an offset into the session there. Keeping the
    comparable part free of either is what makes the comparison possible at all.

    A pairing rather than a subclass because `Claim` is a discriminated union
    and a union cannot be subclassed. That turns out to be the honest shape
    anyway: the claim is the thing, and the page is where it was found.
    """

    model_config = ConfigDict(extra="forbid")

    page: int = Field(gt=0)
    claim: Claim

    #: Whether the quote was found in the deck's own text.
    #:
    #: The difference between a citation that was checked and one that was
    #: accepted. Open Risk #2 is that ungrounded questions kill retention, and
    #: CLAUDE.md refuses interrogation logic that cannot cite its source — so
    #: the panel should be able to tell which of its ammunition is confirmed
    #: verbatim before deciding what to press hardest on.
    #:
    #: False for a figure read off a chart: it lives in the pixels and appears
    #: in no text layer, which is the whole reason a vision model is here. Those
    #: claims are not worse, they are unconfirmable — and being unconfirmable is
    #: worth recording rather than silently mixing in.
    #:
    #: Defaults to False, because a flag that defaults to True is a future
    #: adapter silently asserting a check nothing performed.
    quote_verified: bool = False


@dataclass(frozen=True)
class ExtractionUsage:
    """What one extraction cost, in the units a provider bills in.

    Returned from the interface rather than measured around it, because only the
    adapter knows what the provider charged for. CLAUDE.md makes cost
    instrumentation a required task rather than a later addition, and
    `docs/ingestion.md` is blunt about why it matters *here*: the metering
    boundary is locked to live interrogation, so **extraction is a real per-user
    cost with no revenue attached**, and the abuse case is precisely a deck that
    is extracted and never becomes a session.

    An interface returning only claims would leave that invisible and force
    re-plumbing when `extraction_costs` lands.
    """

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    pages: int

    #: How many requests the adapter made to read those pages. One for a
    #: photograph; fifteen for a full pro-tier deck, which does not fit in any
    #: context window in one piece. Reported because it is the only number that
    #: says whether the chunk size is set anywhere near right — and because
    #: per-call overhead is repeated instruction tokens somebody will eventually
    #: want to see separated from the pages themselves.
    calls: int = 1


@dataclass(frozen=True)
class ExtractionResult:
    claims: tuple[ExtractedClaim, ...]
    usage: ExtractionUsage

    #: Claims the model returned in a shape we could not use. Carried rather
    #: than swallowed: dropping is the right call for one bad entry among forty,
    #: but a silent drop is how a deck quietly grounds nothing.
    dropped: int = 0

    #: Claims whose page the text layer disagreed with, and moved.
    #:
    #: Not an error count — a correction is the mechanism working. It is carried
    #: because the rate is the only measure of how far the model's own page
    #: attribution can be trusted, and that number is what should decide whether
    #: a page stays the locator at all.
    corrected: int = 0

    #: Whether every page of the deck was read.
    #:
    #: A long deck takes several calls, and one of them can fail after the
    #: others have already cost money. When that happens the claims are
    #: discarded and this is false: a partially-read deck grounds less than the
    #: user believes, nothing downstream can tell the difference, and the source
    #: document is deleted on success — so the gap would be permanent and
    #: invisible. `docs/ingestion.md`: *"extraction completeness is a one-way
    #: door, not a backlog item."*
    #:
    #: The usage is still filled in, and that is the point of returning at all
    #: rather than raising. Those calls are on the invoice whether or not their
    #: answers were usable, and cost that cannot be reconciled is worse than
    #: cost that was wasted.
    complete: bool = True


class ExtractionModel(Protocol):
    """Reads pages, returns figures. One instance per process."""

    async def extract(
        self, pages: Sequence[RenderedPage]
    ) -> ExtractionResult:
        """Pull every figure on these pages into typed claims.

        The model's only job. Every *derived* figure — a multiple, a runway, an
        implied valuation — is ordinary arithmetic computed elsewhere, which is
        what makes arithmetic hallucination impossible rather than discouraged
        (`docs/auditor-grounding.md`).
        """
        ...
