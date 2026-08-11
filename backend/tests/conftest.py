import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from app.core.database import Base
from app.modules.billing.models import Account
from app.modules.billing.service import LedgerService

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://flintroom:flintroom@localhost:55432/flintroom_test",
)


@pytest_asyncio.fixture(scope="session")
async def engine():
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


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


@pytest_asyncio.fixture
async def account(db) -> Account:
    """An account with every bucket empty. Minutes arrive only via grants."""
    account = Account(user_id=uuid.uuid4(), entitlement_tier="free")
    db.add(account)
    await db.commit()
    return account
