"""Building a material the way the product does, for tests about what happens next.

Shared because three modules need the same handshake — the sweep, retention,
and the session join that consumes a ready material. A per-module copy drifts,
and the copy that drifts is the one whose test stops exercising the real
upload path and starts asserting against a row somebody built by hand.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from app.modules.ingestion.extraction_model import (
    ExtractedClaim,
    ExtractionResult,
    ExtractionUsage,
)
from app.modules.ingestion.extractor import (
    DEFAULT_DAILY_PAGE_CEILING,
    ExtractionService,
)
from app.modules.ingestion.models import ExtractionCost, Material
from app.modules.ingestion.schemas import QuantitativeClaim, Unit

PDF = "application/pdf"

USAGE = ExtractionUsage(
    provider="claude",
    model="claude-sonnet-5",
    input_tokens=41_200,
    output_tokens=3_100,
    pages=1,
)

MARGIN = ExtractedClaim(
    page=1,
    claim=QuantitativeClaim(
        quote="Gross margin of 61% in Q3 2026",
        metric="gross margin",
        value=61.0,
        unit=Unit.PERCENT,
        period="Q3 2026",
    ),
    quote_verified=True,
)


def reading(*claims: ExtractedClaim, **overrides) -> ExtractionResult:
    """What a model hands back when the call went the way it should."""
    return ExtractionResult(claims=claims, usage=USAGE, **overrides)


class FakeExtractionModel:
    """A model that answers what it was told to answer, and remembers the pages.

    `mocking.md` allows a fake at exactly this boundary: it is the vendor, it
    costs money, and the adapter that talks to it has its own fifty tests. What
    is under test here is the loop around it.
    """

    def __init__(self, result: ExtractionResult | None = None) -> None:
        self.result = result if result is not None else reading()
        self.calls: list[tuple] = []

    async def extract(self, pages):
        self.calls.append(tuple(pages))
        return self.result


async def upload(url: str, body: bytes, content_type: str = PDF) -> None:
    """Do what the phone would do with the URL it was handed."""
    async with httpx.AsyncClient() as http:
        response = await http.put(
            url, content=body, headers={"Content-Type": content_type}
        )
    assert response.status_code == 200, response.text


async def uploaded(ingestion, account, body: bytes) -> Material:
    """A material through the real handshake, sitting in the queue."""
    registered = await ingestion.register(
        user_id=account.user_id,
        filename="q3-board-deck.pdf",
        content_type=PDF,
        byte_size=len(body),
    )
    await upload(registered.upload_url, body)
    return await ingestion.mark_uploaded(
        registered.material.id, user_id=account.user_id
    )


async def claim(ingestion):
    """Take a deck the way the sweep does, with the ceiling out of the way."""
    return await ingestion.claim_for_extraction(
        daily_page_ceiling=DEFAULT_DAILY_PAGE_CEILING
    )


def extraction(db, storage, model) -> ExtractionService:
    return ExtractionService(db, storage=storage, model=model)


async def spent(db, account, pages: int, *, ago: timedelta = timedelta()) -> None:
    """Pages this account has already been billed for.

    Written straight to `extraction_costs` because that table *is* the record
    the budget is counted from — there is no other. Building the spend by
    extracting real decks would need one material per hundred pages and would
    test the fixture rather than the limit.
    """
    db.add(
        ExtractionCost(
            material_id=uuid.uuid4(),
            user_id=account.user_id,
            tier=account.entitlement_tier,
            provider="claude",
            model="claude-sonnet-5",
            pages=pages,
            input_tokens=1,
            output_tokens=1,
            recorded_at=datetime.now(UTC) - ago,
        )
    )
    await db.commit()


async def costs(db, material_id) -> list[ExtractionCost]:
    """What this material has been billed for, attempt by attempt."""
    rows = await db.scalars(
        select(ExtractionCost)
        .where(ExtractionCost.material_id == material_id)
        .order_by(ExtractionCost.recorded_at)
    )
    return list(rows)
