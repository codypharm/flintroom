"""The thing that actually runs the sweeps.

Until this exists the meter and the reaper are functions only tests call: in
production nothing bills and nothing cleans up. It is a loop rather than a task
queue because both sweeps are safe to run twice — the expensive guarantee, that
exactly one runner exists, is one the design deliberately does not need.

Each pass gets its own database session. A session held open across a loop that
lives as long as the process would hold a transaction open just as long, and
every sweep after the first would read a snapshot of the world taken at boot.
"""

import asyncio
import os
import uuid
from datetime import timedelta

import pytest_asyncio
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.main import create_app
from app.modules.billing.schemas import Bucket, EntryReason
from app.modules.sessions.models import Session as SessionModel
from app.modules.sessions.meter import MeterService
from app.modules.sessions.models import SessionPhaseSpan
from app.modules.sessions.runner import SweepRunner
from app.modules.sessions.schemas import SessionState

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://flintroom:flintroom@localhost:55432/flintroom_test",
)


@pytest_asyncio.fixture
async def runner(engine, db) -> SweepRunner:
    """A runner on its own sessions, as it runs in production.

    Deliberately not handed the test's session: a pass that shared it would
    commit the test's staged work as its own and hide exactly the isolation
    mistakes this is here to catch.
    """
    return SweepRunner(async_sessionmaker(engine, expire_on_commit=False))


async def test_the_loop_repeats_and_stops_when_asked(engine, monkeypatch):
    """Runs until shutdown, and then stops without being killed.

    Stopping between passes rather than by cancelling mid-pass: the sweeps write
    money, and a task cancelled inside a commit is the one shutdown that could
    leave a session half-settled. Waiting on the stop signal instead of sleeping
    the interval means shutdown is immediate rather than up to fifteen seconds,
    which is the difference between a rolling deploy and a visible stall.
    """
    passes = 0

    async def counted(self) -> None:
        nonlocal passes
        passes += 1

    monkeypatch.setattr(SweepRunner, "once", counted)
    runner = SweepRunner(async_sessionmaker(engine), interval=0.001)

    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.05)
    runner.stop()
    await asyncio.wait_for(task, timeout=1)

    assert passes > 1
    # And it really stopped, rather than merely being between passes.
    settled = passes
    await asyncio.sleep(0.02)
    assert passes == settled


async def test_the_api_starts_the_sweeps_and_gets_them_back_on_shutdown(monkeypatch):
    """Boot and shutdown, end to end, against a real database.

    The failure this guards is the standard one for background loops: shutdown
    that never completes because nothing tells the task to stop, so every deploy
    hangs until the orchestrator loses patience and kills the process — mid-pass,
    mid-commit, which is how a half-settled session gets made.

    It also proves the wiring exists at all. Everything above tests a runner the
    test constructed; only this proves the running API has one.
    """
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    # Startup builds the OIDC verifiers, so the process now needs its
    # configuration to boot. That is the point — a signing key or a client ID
    # discovered missing at the first sign-in is a deploy that looked healthy.
    monkeypatch.setenv("JWT_SECRET", "a-test-signing-key-of-sufficient-length")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test.apps.googleusercontent.com")
    monkeypatch.setenv("APPLE_CLIENT_ID", "com.flintroom.test")
    get_settings.cache_clear()

    app = create_app()
    before = len(asyncio.all_tasks())

    async with asyncio.timeout(5):
        async with app.router.lifespan_context(app):
            assert len(asyncio.all_tasks()) > before

    assert len(asyncio.all_tasks()) == before


async def test_the_loop_survives_a_pass_that_cannot_reach_the_database():
    """A database blip must not end billing until somebody redeploys.

    The per-sweep guard cannot help here — the failure is in opening the session
    the sweeps would have used, before either of them runs. This is also the
    likeliest failure in production by a wide margin: a restart on the database
    side, or a pool exhausted for a few seconds. The loop has to come back on
    its own, because nothing else is watching it.
    """
    attempts = 0

    def unreachable():
        nonlocal attempts
        attempts += 1
        raise OSError("connection refused")

    runner = SweepRunner(unreachable, interval=0.001)

    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.05)
    runner.stop()
    await asyncio.wait_for(task, timeout=1)

    assert attempts > 1


async def test_a_broken_sweep_does_not_stop_the_other_one(
    runner, sessions, account, db, monkeypatch
):
    """A bug in billing must not also stop rooms being cleaned up.

    The two sweeps share a pass for convenience, not because either depends on
    the other. Fused failure would mean a defect in the meter — the more
    intricate of the two — silently leaves every user's lock held by a session
    nobody can end, turning a billing bug into an outage of the whole product.
    """

    async def broken(self) -> None:
        raise RuntimeError("meter is having a bad day")

    monkeypatch.setattr(MeterService, "sweep", broken)

    stuck = await sessions.start(user_id=account.user_id)
    await db.execute(
        update(SessionModel)
        .where(SessionModel.id == stuck.id)
        .values(last_progress_at=func.now() - timedelta(seconds=180))
    )
    await db.commit()

    await runner.once()

    assert (await sessions.get(session_id=stuck.id)).state is SessionState.FAILED


async def test_one_pass_bills_a_live_room_and_reaps_a_stuck_one(
    runner, sessions, ledger, account, db
):
    """The tracer: both sweeps are wired, and they run against real sessions.

    Together rather than in two passes because they are two halves of one
    caretaking job — the reaper closes what the meter can no longer bill, and a
    deployment that started one without the other would either bill rooms
    nobody can end or end rooms nobody billed.
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=600,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )
    live = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=live.id)
    await db.execute(
        update(SessionPhaseSpan)
        .where(SessionPhaseSpan.session_id == live.id)
        .values(started_at=func.now() - timedelta(seconds=15))
    )
    await db.commit()

    stuck = await sessions.start(user_id=uuid.uuid4())
    await db.execute(
        update(SessionModel)
        .where(SessionModel.id == stuck.id)
        .values(last_progress_at=func.now() - timedelta(seconds=180))
    )
    await db.commit()

    await runner.once()

    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == 585
    assert (await sessions.get(session_id=stuck.id)).state is SessionState.FAILED
