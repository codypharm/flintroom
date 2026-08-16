"""The sweep — what turns an uploaded deck into claims without anyone asking.

Everything before this slice is reachable only by hand: a material could be
registered, uploaded and settled, and nothing in the process ever moved one from
`pending` to `ready`. This is the loop that does, and the properties that matter
are the ones nobody watches — that a claimed deck is released when the process
holding it dies, that a busy minute does not fail somebody's file, and that a
runaway cannot spend without bound.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.billing.tiers import (
    FREE_TIER_LIFETIME_PAGES,
    MONTHLY_PAGE_BUDGET,
)
from app.modules.ingestion.extractor import (
    DEFAULT_DAILY_PAGE_CEILING,
    EXTRACTION_TIMEOUT,
)
from app.modules.ingestion.models import Material
from app.modules.ingestion.runner import ExtractionRunner
from app.modules.ingestion.schemas import MaterialState
from tests.materials import (
    MARGIN,
    FakeExtractionModel,
    claim,
    costs,
    extraction,
    reading,
    spent,
    uploaded,
)
from tests.pdfs import minimal_pdf


async def test_an_uploaded_deck_becomes_claims(db, ingestion, storage, account):
    """The tracer bullet: nobody asks, and the deck is read anyway.

    Deliberately the whole path — the real store, a real PDF, the real parser —
    because every seam between them is a place a deck can be silently lost, and
    a sweep proved correct against fakes has proved that two fakes agree.
    """
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(MARGIN))

    assert await extraction(db, storage, model).sweep() is True

    await db.refresh(material)
    assert material.state is MaterialState.READY

    claims = await ingestion.claims(material.id, user_id=account.user_id)
    assert [claim.claim.metric for claim in claims] == ["gross margin"]


async def test_a_busy_minute_gives_the_deck_back_rather_than_failing_it(
    db, ingestion, storage, account
):
    """A rate limit is our capacity problem, not the user's file.

    `failed` is terminal and tells the user to re-upload, so reading a
    throughput event as "this deck is unreadable" turns a slow evening into data
    loss. Under load retries exhaust unevenly, which makes this the *likely*
    shape of a rate-limit event rather than a rare one.
    """
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(complete=False, retryable=True))

    assert await extraction(db, storage, model).sweep() is True

    await db.refresh(material)
    assert material.state is MaterialState.PENDING
    assert material.attempts == 1
    assert material.retry_at is not None


async def test_a_deck_that_was_given_back_waits_before_it_is_claimed_again(
    db, ingestion, storage, account
):
    """The backoff is on the row, so the claim query has to honour it.

    Without this the wait is decoration: a requeued deck is picked up on the
    very next pass, and a rate-limit event becomes a tight loop against the
    limit that caused it. Nothing else fails when this is forgotten — the deck
    still eventually extracts, and only the provider notices.
    """
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(complete=False, retryable=True))
    sweep = extraction(db, storage, model)

    await sweep.sweep()
    assert await sweep.sweep() is False

    await db.refresh(material)
    assert material.state is MaterialState.PENDING
    assert material.attempts == 1


async def test_a_deck_the_provider_refuses_outright_is_not_retried(
    db, ingestion, storage, account
):
    """Not retryable means the answer will not change, so stop paying for it.

    The adapter only reports this when a sibling chunk succeeded, which is the
    evidence that the request shape works — so reaching here means the deck
    itself is the problem and every further attempt buys the same refusal.
    """
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(complete=False, retryable=False))

    assert await extraction(db, storage, model).sweep() is True

    await db.refresh(material)
    assert material.state is MaterialState.FAILED
    assert material.attempts == 0


async def test_a_deck_whose_worker_died_is_taken_back_and_read(
    db, ingestion, storage, account
):
    """`extracting` is a claim, and a claim outlives the process holding it.

    The same crash-safety problem the `finalizing` session state already solves
    — *"nothing separates 'finished settling' from 'died halfway'"* — and it has
    the same answer. Without it a deployment mid-extraction strands the deck in
    `extracting` forever: no sweep will claim it, no user action can clear it,
    and the material simply never becomes ready.
    """
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    assert await claim(ingestion) is not None

    # The worker is gone. Nothing wrote a result, and the row still says busy.
    material.claimed_at = datetime.now(UTC) - EXTRACTION_TIMEOUT - timedelta(minutes=1)
    await db.commit()

    model = FakeExtractionModel(reading(MARGIN))
    assert await extraction(db, storage, model).sweep() is True

    await db.refresh(material)
    assert material.state is MaterialState.READY
    # Counted, so a deck that reliably kills the worker cannot be claimed
    # forever. A crash is not the file's fault, but it is not free either.
    assert material.attempts == 1


async def test_a_deck_still_being_read_is_left_alone(
    db, ingestion, storage, account
):
    """The timeout has to clear a slow extraction, not merely a dead one.

    A pro-tier deck is fifteen model calls, and taking it back while those are
    in flight is how one deck becomes two invoices — the exact duplication the
    claim exists to prevent.
    """
    await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    assert await claim(ingestion) is not None

    model = FakeExtractionModel(reading(MARGIN))
    assert await extraction(db, storage, model).sweep() is False
    assert model.calls == []


async def test_a_deck_over_the_tier_cap_fails_without_being_read(
    db, ingestion, storage, account
):
    """Terminal, and the distinction from a budget is the whole point.

    `docs/ingestion.md` was corrected on this: no window rolls over into a file
    being shorter, so leaving it `pending` would have a four-hundred-page deck
    claimed by every pass forever, failing identically and charging for the
    attempt. The model must not be reached — the cap exists to stop the bill,
    and a cap applied after the call is a bill followed by a refusal.
    """
    deck = minimal_pdf(*(f"Slide {number}" for number in range(25)))
    material = await uploaded(ingestion, account, deck)
    model = FakeExtractionModel(reading(MARGIN))

    assert await extraction(db, storage, model).sweep() is True

    await db.refresh(material)
    assert material.state is MaterialState.FAILED
    assert model.calls == []
    assert await costs(db, material.id) == []


async def test_a_deck_whose_object_vanished_fails_rather_than_waiting(
    db, ingestion, storage, account
):
    """Nothing about waiting makes a deleted object come back.

    The handshake HEADs the store before queueing precisely so this is rare,
    but an object can go between then and here. Treating it as retryable would
    spend ten attempts over several hours to reach the same answer.
    """
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    await storage.delete(material.storage_key)
    model = FakeExtractionModel(reading(MARGIN))

    assert await extraction(db, storage, model).sweep() is True

    await db.refresh(material)
    assert material.state is MaterialState.FAILED
    assert model.calls == []


async def test_a_user_over_their_page_budget_waits_rather_than_fails(
    db, ingestion, storage, account
):
    """A budget is a window, and a window rolls over. The file is fine.

    So the material stays `pending` and is simply not claimed — and it must not
    be claimed, rather than claimed and put back. A refusal *after* the claim
    would burn one of the ten retryable attempts on every pass until the window
    moved, and the deck would be `failed` long before it was ever allowed to
    extract.
    """
    await spent(db, account, FREE_TIER_LIFETIME_PAGES)
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(MARGIN))

    assert await extraction(db, storage, model).sweep() is False

    await db.refresh(material)
    assert material.state is MaterialState.PENDING
    assert material.attempts == 0


async def test_one_page_under_the_budget_still_extracts(
    db, ingestion, storage, account
):
    """The other half, and the one a mistake in the comparison would break.

    Without it, a budget written `<=` where it meant `<` refuses everybody at
    exactly the figure the tier card sells, and nothing else notices.
    """
    await spent(db, account, FREE_TIER_LIFETIME_PAGES - 1)
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(MARGIN))

    assert await extraction(db, storage, model).sweep() is True

    await db.refresh(material)
    assert material.state is MaterialState.READY


async def test_one_users_exhausted_budget_does_not_block_the_queue(
    db, ingestion, storage, account, funded_account
):
    """Head-of-line blocking, which is what makes this a query and not a check.

    The oldest deck belongs to somebody with nothing left. Were the budget read
    after picking a candidate, the sweep would pick that one every pass, decline
    it, and do no work at all — one user's exhausted allowance stopping
    extraction for everybody.
    """
    await spent(db, account, FREE_TIER_LIFETIME_PAGES)
    blocked = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    waiting = await uploaded(ingestion, funded_account, minimal_pdf("Revenue up 40%"))
    model = FakeExtractionModel(reading(MARGIN))

    assert await extraction(db, storage, model).sweep() is True

    await db.refresh(blocked)
    await db.refresh(waiting)
    assert blocked.state is MaterialState.PENDING
    assert waiting.state is MaterialState.READY


async def test_a_daily_ceiling_stops_a_runaway_inside_the_monthly_budget(
    db, ingestion, storage, account
):
    """Two controls, two jobs.

    The monthly budget protects margin, which is measured monthly. This one is a
    circuit breaker against a loop, a bug or a script, and a single number cannot
    do both: rehearsal is bursty by the same logic that put the minutes allowance
    on a monthly reset, so a ceiling loose enough for a real preparation evening
    is catastrophic if drawn every day for a month.
    """
    account.entitlement_tier = "pro"
    account.period_ends_at = datetime.now(UTC) + timedelta(days=10)
    await db.commit()
    await spent(db, account, DEFAULT_DAILY_PAGE_CEILING)

    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(MARGIN))

    assert await extraction(db, storage, model).sweep() is False

    await db.refresh(material)
    assert material.state is MaterialState.PENDING


async def test_yesterdays_pages_do_not_count_against_todays_ceiling(
    db, ingestion, storage, account
):
    """The ceiling is a rolling day, so it has to actually roll.

    One that never releases is not a circuit breaker but a lifetime cap nobody
    agreed to, and it would present as extraction silently stopping for a user
    who did nothing wrong.
    """
    account.entitlement_tier = "pro"
    account.period_ends_at = datetime.now(UTC) + timedelta(days=10)
    await db.commit()
    await spent(db, account, DEFAULT_DAILY_PAGE_CEILING, ago=timedelta(days=1, hours=1))

    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(MARGIN))

    assert await extraction(db, storage, model).sweep() is True

    await db.refresh(material)
    assert material.state is MaterialState.READY


async def test_the_free_tiers_budget_is_lifetime_and_never_rolls_over(
    db, ingestion, storage, account
):
    """The faucet this closes: sign up, never start a session, extract forever.

    Free minutes are lifetime — granted once, deliberately absent from the
    monthly table — so a renewing page budget on a tier whose minutes do not
    renew is unbounded cost with no metered minute ever consumed against it.
    """
    await spent(db, account, FREE_TIER_LIFETIME_PAGES, ago=timedelta(days=400))
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(MARGIN))

    assert await extraction(db, storage, model).sweep() is False

    await db.refresh(material)
    assert material.state is MaterialState.PENDING


async def test_a_paid_tiers_budget_rolls_with_its_entitlement_period(
    db, ingestion, storage, account
):
    """The contrast that keeps the test above honest.

    Same spend and the same shape, on a tier whose window moves — so a budget
    accidentally written as lifetime for everybody fails here rather than in a
    support ticket from somebody who paid.
    """
    account.entitlement_tier = "starter"
    account.period_ends_at = datetime.now(UTC) + timedelta(days=10)
    await db.commit()
    await spent(db, account, MONTHLY_PAGE_BUDGET["starter"], ago=timedelta(days=45))

    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    model = FakeExtractionModel(reading(MARGIN))

    assert await extraction(db, storage, model).sweep() is True

    await db.refresh(material)
    assert material.state is MaterialState.READY


async def test_the_runner_drains_a_queue_without_waiting_between_decks(
    engine, ingestion, storage, account
):
    """Two decks, one interval. The loop must not pace itself while there is work.

    The interval here is a minute, so a runner that slept between decks would
    hang this test rather than fail it — which is the point. A user who uploads
    during a backlog otherwise waits one interval per deck ahead of them, and
    that is invisible until the queue is long enough to matter.
    """
    first = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))
    second = await uploaded(ingestion, account, minimal_pdf("Revenue up 40%"))

    factory = async_sessionmaker(engine, expire_on_commit=False)
    runner = ExtractionRunner(
        factory,
        storage=storage,
        model=FakeExtractionModel(reading(MARGIN)),
        interval=60.0,
    )
    task = asyncio.create_task(runner.run())

    try:
        await settled(factory, first.id, second.id)
    finally:
        runner.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def settled(factory, *material_ids, timeout: float = 10.0) -> None:
    """Wait for every material to leave the queue, or say what it was still doing."""
    deadline = asyncio.get_running_loop().time() + timeout
    states: list = []

    while asyncio.get_running_loop().time() < deadline:
        async with factory() as db:
            states = [
                (await db.get(Material, material_id)).state
                for material_id in material_ids
            ]
        if all(state is MaterialState.READY for state in states):
            return
        await asyncio.sleep(0.02)

    pytest.fail(f"materials never became ready: {states}")
