import asyncio
import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from app.core.database import Base
from app.modules.audit_log.models import AuditEvent  # noqa: F401  (registers the table)
from app.modules.billing.models import Account
from app.modules.audit_log.admin import AdminService
from app.modules.audit_log.service import AuditService
from app.modules.billing.service import LedgerService
from app.modules.sessions.models import (  # noqa: F401  (registers the tables)
    Session,
    SessionPhaseSpan,
)
from app.modules.sessions.service import SessionService
from app.modules.sessions.settlement import SettlementService

BACKEND_ROOT = Path(__file__).resolve().parent.parent

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://flintroom:flintroom@localhost:55432/flintroom_test",
)


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Build the schema by running the migrations, not from model metadata.

    `create_all` would test the models against themselves and never execute a
    migration, so a missing or wrong migration would pass every test and fail
    on deploy. Running them here means the migration chain is exercised on every
    test run, and a model change without a migration shows up as a failure.
    """
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    await asyncio.to_thread(_upgrade_to_head)

    yield engine
    await engine.dispose()


def _upgrade_to_head() -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    command.upgrade(config, "head")


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    """A session per test, with every table emptied first."""
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
def ledger(db) -> LedgerService:
    return LedgerService(db)


@pytest.fixture
def audit(db) -> AuditService:
    return AuditService(db)


@pytest.fixture
def admin(db) -> AdminService:
    return AdminService(db)


@pytest.fixture
def sessions(db) -> SessionService:
    return SessionService(db)


@pytest_asyncio.fixture
async def account(db) -> Account:
    """An account with every bucket empty. Minutes arrive only via grants."""
    account = Account(user_id=uuid.uuid4(), entitlement_tier="free")
    db.add(account)
    await db.commit()
    return account


@pytest.fixture
def settlement(db) -> SettlementService:
    return SettlementService(db)
