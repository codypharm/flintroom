"""What survives a deck — the claims, and what reading it cost.

The source document is deleted once extraction succeeds (`docs/ingestion.md`),
so these rows are not a cache of the file. They are the file, as far as
everything downstream is concerned, and anything the extraction did not write
here is permanently gone.
"""

import logging
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.errors import (
    ExtractionIncomplete,
    InvalidMaterialState,
    MaterialNotFound,
)
from app.modules.ingestion.extraction_model import (
    ExtractedClaim,
    ExtractionResult,
    ExtractionUsage,
)
from app.modules.ingestion.models import ExtractionCost, Material, MaterialClaim
from app.modules.ingestion.schemas import (
    AssertionClaim,
    MAX_FIGURE,
    MaterialState,
    QuantitativeClaim,
    Unit,
)

USAGE = ExtractionUsage(
    provider="claude",
    model="claude-sonnet-5",
    input_tokens=41_200,
    output_tokens=3_100,
    pages=12,
)

MARGIN = ExtractedClaim(
    page=7,
    claim=QuantitativeClaim(
        quote="Gross margin of 61% in Q3 2026",
        metric="gross margin",
        value=61.0,
        unit=Unit.PERCENT,
        period="Q3 2026",
    ),
    quote_verified=True,
)

EXCLUSIVE = ExtractedClaim(
    page=9,
    claim=AssertionClaim(
        quote="Our distribution agreement with Northwind is exclusive",
        subject="distribution",
        statement="The Northwind distribution agreement is exclusive",
    ),
)


async def extracting_material(db, account) -> Material:
    """A material the sweep has taken, ready to be settled.

    Built directly rather than through the service because nothing claims a
    material yet — the sweep is slice 6. What this slice owns is what happens
    once a model has answered.
    """
    material = Material(
        id=uuid.uuid4(),
        user_id=account.user_id,
        state=MaterialState.EXTRACTING,
        filename="q3-board-deck.pdf",
        content_type="application/pdf",
        byte_size=2_400_000,
        storage_key=f"material/{account.user_id}/{uuid.uuid4()}",
        claimed_at=datetime.now(UTC),
    )
    db.add(material)
    await db.commit()
    return material


async def test_settling_an_extraction_stores_its_claims(ingestion, account, db):
    """The tracer: a model answered, and the answer outlived the file."""
    material = await extracting_material(db, account)

    await ingestion.settle_extraction(
        material.id, result=ExtractionResult(claims=(MARGIN,), usage=USAGE)
    )

    claims = await ingestion.claims(material.id, user_id=account.user_id)
    assert [claim.claim.quote for claim in claims] == [MARGIN.claim.quote]


async def test_a_figure_survives_the_round_trip_comparable(ingestion, account, db):
    """Storage must not be where comparability is lost.

    `docs/auditor-grounding.md`: *"most false positives come from comparing
    figures that were never comparable."* Unit and period are what make the
    comparison legal, so a round trip that drops either turns a stored figure
    into one that agrees with anything.
    """
    material = await extracting_material(db, account)
    await ingestion.settle_extraction(
        material.id, result=ExtractionResult(claims=(MARGIN,), usage=USAGE)
    )

    stored = (await ingestion.claims(material.id, user_id=account.user_id))[0]

    assert stored.claim.comparable_to(MARGIN.claim)
    assert stored.claim.value == MARGIN.claim.value
    assert stored.page == MARGIN.page
    assert stored.quote_verified is True


async def test_an_assertion_survives_with_its_subject(ingestion, account, db):
    """The subject is what makes targeted interruption possible.

    §3.3 assigns the interrupter by domain — the CFO archetype catches a margin
    contradiction, not the Technical Skeptic. An assertion stored without its
    subject is unroutable, and targeted interruption quietly covers only
    numbers.
    """
    material = await extracting_material(db, account)
    await ingestion.settle_extraction(
        material.id, result=ExtractionResult(claims=(EXCLUSIVE,), usage=USAGE)
    )

    stored = (await ingestion.claims(material.id, user_id=account.user_id))[0]

    assert stored.claim == EXCLUSIVE.claim
    assert stored.quote_verified is False


async def test_a_figure_too_large_for_the_column_never_reaches_it(ingestion, account, db):
    """A hallucinated magnitude must not take the whole deck down with it.

    `value` is `Numeric(20, 6)`, so a figure past fourteen digits is a write the
    database refuses — and settling is one transaction, so that one entry would
    cost every other claim on the deck. The material would stay `extracting`,
    be requeued, and fail identically every time while charging for each
    attempt.

    Refused by the type instead, where the adapter's existing drop path counts
    it. A hundred trillion is past any figure a real deck asserts, so nothing
    legitimate is lost by putting the bound where the column is.
    """
    with pytest.raises(ValidationError):
        QuantitativeClaim(
            quote="Total addressable market of $1e20",
            metric="TAM",
            value=1e20,
            unit=Unit.USD,
        )


async def test_the_largest_permitted_figure_actually_fits_the_column(
    ingestion, account, db
):
    """The bound is only useful if it matches the column, both ways.

    A bound below the column loses real figures; a bound above it is the
    original hazard with an extra step. This asserts the top of the range
    survives a real write rather than trusting the arithmetic behind
    `Numeric(20, 6)`.
    """
    material = await extracting_material(db, account)
    huge = ExtractedClaim(
        page=2,
        claim=QuantitativeClaim(
            quote="A market worth $99,999,999,999,999",
            metric="TAM",
            value=float(MAX_FIGURE),
            unit=Unit.USD,
        ),
    )

    await ingestion.settle_extraction(
        material.id, result=ExtractionResult(claims=(huge,), usage=USAGE)
    )

    stored = (await ingestion.claims(material.id, user_id=account.user_id))[0]
    assert stored.claim.value == float(MAX_FIGURE)


async def _cost_rows(db, material_id) -> list[ExtractionCost]:
    """Read the telemetry directly, as `test_session_costs.py` does.

    No service method returns these: nothing user-facing reads them, and an
    endpoint that did would publish per-user cost. The table is the interface.
    """
    rows = await db.scalars(
        select(ExtractionCost)
        .where(ExtractionCost.material_id == material_id)
        .order_by(ExtractionCost.recorded_at)
    )
    return list(rows)


async def test_reading_a_deck_leaves_a_cost_row(ingestion, account, db):
    """Extraction is a real per-user cost with no revenue attached.

    The metering boundary is locked to live interrogation, so the abuse case is
    precisely a deck that is extracted and never becomes a session. Attributing
    this to the session that used the material would leave exactly that case
    invisible — which is why the row is keyed to the material and the user, and
    written whether or not a session ever follows.
    """
    material = await extracting_material(db, account)

    await ingestion.settle_extraction(
        material.id, result=ExtractionResult(claims=(MARGIN, EXCLUSIVE), usage=USAGE)
    )

    [cost] = await _cost_rows(db, material.id)
    assert cost.user_id == account.user_id
    assert cost.tier == account.entitlement_tier
    assert (cost.provider, cost.model) == (USAGE.provider, USAGE.model)
    assert (cost.input_tokens, cost.output_tokens) == (
        USAGE.input_tokens,
        USAGE.output_tokens,
    )
    assert (cost.pages, cost.claims_recorded) == (USAGE.pages, 2)


async def test_the_tier_is_frozen_at_the_time_of_extraction(ingestion, account, db):
    """Cost analysis groups by tier, and a user's tier changes.

    Read live, an upgrade would re-price every extraction that account ever
    ran — including the ones that made the case for setting the free tier's
    page cap where it is.
    """
    material = await extracting_material(db, account)
    await ingestion.settle_extraction(
        material.id, result=ExtractionResult(claims=(), usage=USAGE)
    )

    account.entitlement_tier = "pro"
    await db.commit()

    [cost] = await _cost_rows(db, material.id)
    assert cost.tier == "free"


async def test_only_a_claimed_material_can_be_settled(ingestion, account, db):
    """Settling twice is a second set of claims and a second invoice.

    The `extracting` mark is what a sweep holds while it works, so requiring it
    here is the same check that stops two workers settling the same material —
    and the same one that stops a settle arriving for a deck nobody ever
    extracted.
    """
    material = await extracting_material(db, account)
    await ingestion.settle_extraction(
        material.id, result=ExtractionResult(claims=(MARGIN,), usage=USAGE)
    )

    with pytest.raises(InvalidMaterialState):
        await ingestion.settle_extraction(
            material.id, result=ExtractionResult(claims=(MARGIN,), usage=USAGE)
        )

    assert len(await ingestion.claims(material.id, user_id=account.user_id)) == 1
    assert len(await _cost_rows(db, material.id)) == 1


async def test_a_settled_material_releases_its_claim_mark(ingestion, account, db):
    """`claimed_at` and `extracting` are one fact, and a CHECK says so.

    A settled row still carrying the mark would fail the write outright; a
    `ready` row that somehow kept it would be invisible to the requeue sweep
    while looking busy forever.
    """
    material = await extracting_material(db, account)

    settled = await ingestion.settle_extraction(
        material.id, result=ExtractionResult(claims=(), usage=USAGE)
    )

    assert settled.state is MaterialState.READY
    assert settled.claimed_at is None


async def test_a_requeued_extraction_records_the_second_invoice(
    ingestion, account, db
):
    """A stalled claim is requeued by design, and a requeue costs money again.

    Keyed on `material_id` alone the table would refuse the second row or
    overwrite the first, and both under-report what was actually spent. One row
    per attempt is what makes a deck that was read twice look like a deck that
    was read twice.
    """
    material = await extracting_material(db, account)
    await ingestion.settle_extraction(
        material.id, result=ExtractionResult(claims=(), usage=USAGE)
    )

    material.state = MaterialState.EXTRACTING
    material.claimed_at = datetime.now(UTC)
    await db.commit()
    await ingestion.settle_extraction(
        material.id, result=ExtractionResult(claims=(), usage=USAGE)
    )

    assert len(await _cost_rows(db, material.id)) == 2


async def test_deleting_a_material_takes_its_claims_and_leaves_its_cost(
    ingestion, account, db
):
    """The two tables have deliberately different answers to a deletion.

    A claim outliving its material is a fragment of a document the user believes
    they deleted, so it cascades. The cost row must not: materials are
    user-deletable, and cascading there would let "upload, extract, delete,
    repeat" erase its own trail — the one shape of usage §4.3 exists to make
    visible would be the one leaving no record.
    """
    material = await extracting_material(db, account)
    await ingestion.settle_extraction(
        material.id, result=ExtractionResult(claims=(MARGIN, EXCLUSIVE), usage=USAGE)
    )

    await db.delete(material)
    await db.commit()

    surviving = await db.scalar(
        select(func.count())
        .select_from(MaterialClaim)
        .where(MaterialClaim.material_id == material.id)
    )
    assert surviving == 0
    assert len(await _cost_rows(db, material.id)) == 1


async def test_another_account_cannot_read_a_deck_it_does_not_own(
    ingestion, account, db
):
    """Not-found and not-yours are the same answer, for the same reason as `get`.

    A deck is the most confidential thing this product holds, and telling a
    prober which material ids exist is the first half of reading one.
    """
    material = await extracting_material(db, account)
    await ingestion.settle_extraction(
        material.id, result=ExtractionResult(claims=(MARGIN,), usage=USAGE)
    )

    with pytest.raises(MaterialNotFound):
        await ingestion.claims(material.id, user_id=uuid.uuid4())


async def test_claims_come_back_in_reading_order(ingestion, account, db):
    """The panel works through a deck the way the room does.

    Returned sorted rather than left to insertion order, because a chunked
    extraction (task #31) settles pages out of order and nothing downstream
    should have to know that.
    """
    material = await extracting_material(db, account)
    later = MARGIN.model_copy(update={"page": 11})
    earlier = EXCLUSIVE.model_copy(update={"page": 2})

    await ingestion.settle_extraction(
        material.id, result=ExtractionResult(claims=(later, earlier), usage=USAGE)
    )

    stored = await ingestion.claims(material.id, user_id=account.user_id)
    assert [claim.page for claim in stored] == [2, 11]


@pytest.mark.parametrize(
    ("kind", "columns", "why"),
    [
        (
            "assertion",
            {"metric": "gross margin", "value": 61, "unit": "percent"},
            "an assertion carrying a figure",
        ),
        (
            "quantitative",
            {"subject": "distribution", "statement": "exclusive"},
            "a figure carrying an assertion",
        ),
        ("quantitative", {}, "a figure with no metric at all"),
        ("assertion", {}, "an assertion with no statement"),
    ],
)
async def test_a_claim_cannot_be_half_of_each_kind(db, account, kind, columns, why):
    """The CHECK is the reason the wide table is safe.

    Two implications would have permitted the first case here — an assertion
    that also carries a metric. Nothing reads that row expecting both, so every
    reader would interpret it differently, and the constraint is what stops one
    ever existing. Written by hand rather than through the service, because the
    service is exactly what a future direct writer would not be going through.
    """
    material = await extracting_material(db, account)
    values = {
        "id": uuid.uuid4(),
        "material_id": material.id,
        "user_id": account.user_id,
        "page": 1,
        "kind": kind,
        "quote": "whatever the slide said",
        "quote_verified": False,
        **columns,
    }
    names = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)

    with pytest.raises(IntegrityError):
        await db.execute(
            text(f"INSERT INTO material_claims ({names}) VALUES ({binds})"), values
        )


async def test_a_control_byte_in_a_quote_does_not_destroy_the_deck(
    ingestion, account, db
):
    """A PDF text layer can carry bytes Postgres will not store.

    A NUL is not valid UTF-8 to Postgres, and settling is one transaction — so
    one stray byte in one quote would refuse every claim on the deck, leave the
    material `extracting`, and be requeued to fail identically while charging
    for each attempt. The surrounding words are still a perfectly good citation,
    so the byte is dropped rather than the claim.
    """
    material = await extracting_material(db, account)
    dirty = ExtractedClaim(
        page=3,
        claim=QuantitativeClaim(
            quote="Gross\x00 margin of 61%",
            metric="gross\x00 margin",
            value=61.0,
            unit=Unit.PERCENT,
        ),
    )

    await ingestion.settle_extraction(
        material.id, result=ExtractionResult(claims=(dirty,), usage=USAGE)
    )

    stored = (await ingestion.claims(material.id, user_id=account.user_id))[0]
    assert stored.claim.quote == "Gross margin of 61%"
    assert stored.claim.metric == "gross margin"


async def test_a_quote_that_quotes_nothing_is_refused(ingestion, account, db):
    """Stripping is not a licence to store an empty citation.

    `min_length` is checked after the strip, so a quote that was only control
    characters fails validation and lands in the adapter's drop path — counted,
    not silently written as a claim citing nothing.
    """
    with pytest.raises(ValidationError):
        AssertionClaim(
            quote="\x00\x01\x02",
            subject="distribution",
            statement="The agreement is exclusive",
        )


async def test_settling_never_logs_what_the_deck_said(ingestion, account, db, caplog):
    """Ingested material contents are forbidden in logs (CLAUDE.md).

    Unlike a secret, a quote is not detectable by key name, so the redactor
    cannot save us — the text has to never be passed to a log call. Asserted
    against every record rather than one line, because the leak that matters is
    the one added later by somebody debugging.
    """
    material = await extracting_material(db, account)

    with caplog.at_level(logging.DEBUG):
        await ingestion.settle_extraction(
            material.id,
            result=ExtractionResult(claims=(MARGIN, EXCLUSIVE), usage=USAGE),
        )

    logged = "\n".join(
        record.getMessage() + repr(record.__dict__) for record in caplog.records
    )
    assert MARGIN.claim.quote not in logged
    assert EXCLUSIVE.claim.statement not in logged
    assert "gross margin" not in logged


INCOMPLETE = ExtractionResult(claims=(), usage=USAGE, complete=False)


async def test_a_half_read_deck_is_never_settled_as_ready(ingestion, account, db):
    """`ready` is a promise the panel relies on.

    A long deck takes several calls and one can fail after the others have been
    paid for. Marking that material ready would hand the panel a deck it grounds
    less of than anyone believes — and since the source is deleted on success,
    the gap would be permanent and invisible.
    """
    material = await extracting_material(db, account)

    with pytest.raises(ExtractionIncomplete):
        await ingestion.settle_extraction(material.id, result=INCOMPLETE)

    assert material.state is MaterialState.EXTRACTING


async def test_a_failed_extraction_is_still_paid_for(ingestion, account, db):
    """The calls that succeeded are on the invoice either way.

    §4.3 measures margin against observed spend, not against spend that
    happened to produce something — and the abuse case is a deck extracted and
    never used, which looks identical whether or not the extraction finished.
    """
    material = await extracting_material(db, account)

    failed = await ingestion.fail_extraction(material.id, result=INCOMPLETE)

    assert failed.state is MaterialState.FAILED
    assert failed.claimed_at is None

    [cost] = await _cost_rows(db, material.id)
    assert cost.input_tokens == USAGE.input_tokens
    assert cost.claims_recorded == 0


async def test_a_failed_extraction_stores_no_claims(ingestion, account, db):
    """Failing is not a quieter way of storing part of a deck."""
    material = await extracting_material(db, account)

    await ingestion.fail_extraction(
        material.id,
        result=ExtractionResult(claims=(MARGIN,), usage=USAGE, complete=False),
    )

    stored = await db.scalar(
        select(func.count())
        .select_from(MaterialClaim)
        .where(MaterialClaim.material_id == material.id)
    )
    assert stored == 0
