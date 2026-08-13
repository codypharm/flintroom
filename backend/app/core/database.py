import os
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every Flintroom ORM model."""


def create_engine(url: str | None = None) -> AsyncEngine:
    """The process's connection pool.

    Read from the environment rather than a settings object because there is no
    settings module yet, and inventing one means choosing a configuration
    library — a dependency decision that belongs to the human, not to this
    function needing a connection string.

    Fails at startup if unset. A process that boots without a database and
    discovers it on the first sweep looks healthy to every deploy check while
    silently billing nobody.
    """
    resolved = url or os.getenv("DATABASE_URL")
    if not resolved:
        raise RuntimeError("DATABASE_URL is not set")
    return create_async_engine(resolved)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request, closed when the response is done.

    Taken from application state rather than a module-level global so that the
    factory is built once at startup, by the lifespan that also owns disposing
    of it — and so a test can substitute a session without a running engine.

    No commit here. Services own their transaction boundaries because they are
    the only thing that knows what a complete unit of work is; a dependency that
    commits on the way out would commit half-finished ones too.
    """
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


async def db_now(db: AsyncSession) -> datetime:
    """The database's clock, for any timestamp another timestamp is compared to.

    Several columns take their value from `server_default=func.now()`, which is
    the database's clock. Writing the other end of the same pair from Python
    compares two clocks on two machines: NTP holds them within milliseconds of
    each other, not identical, and a phase span can open and close inside that
    gap. `ck_spans_ordering` then rejects the write, and the rejection lands
    during finalisation — leaving the span open, which bills forever on every
    replay of the ledger.

    Reading the clock costs a round trip inside a transaction that is already
    open. That is the price of both ends of a comparison coming from the same
    place, and it is worth paying every time.

    This is `transaction_timestamp()`, matching `func.now()` exactly rather than
    approximating it — so a row written and compared in one transaction sees
    consistent values, and the equal case satisfies a `>=` constraint.
    """
    return await db.scalar(select(func.now()))


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Sessions for work that has no request behind it.

    `expire_on_commit` off for the reason the sweeps document at length: a
    commit or rollback that expires mapped objects makes the next attribute read
    a lazy database call, which in async code surfaces as `MissingGreenlet`
    rather than as anything resembling its cause.
    """
    return async_sessionmaker(engine, expire_on_commit=False)
