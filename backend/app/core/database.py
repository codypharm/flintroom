from collections.abc import AsyncIterator
from datetime import datetime

from starlette.requests import HTTPConnection
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


def create_engine(url: str) -> AsyncEngine:
    """The process's connection pool.

    Handed the URL rather than looking one up. It used to read `os.getenv`
    itself, on the grounds that there was no settings module yet — there is one
    now, and the reading it was doing never saw `.env`, so a connection string
    configured there was accepted by the file and ignored by the process.

    Required, with no fallback, so that the one place a missing database is
    caught is the one place that validates every other variable too.
    """
    return create_async_engine(url)


async def get_db(connection: HTTPConnection) -> AsyncIterator[AsyncSession]:
    """One session per request, closed when the response is done.

    Taken from application state rather than a module-level global so that the
    factory is built once at startup, by the lifespan that also owns disposing
    of it — and so a test can substitute a session without a running engine.

    `HTTPConnection` rather than `Request`, because this also serves the stream
    socket and a WebSocket is not a `Request`. FastAPI could not build the
    argument, so every attempt to open a room died in dependency resolution with
    `get_db() missing 1 required positional argument` — a 500 on the handshake,
    before any of our code ran, on a route that had never been opened for real.
    `HTTPConnection` is the common base of both and carries `.app`, which is all
    this needs.

    No commit here. Services own their transaction boundaries because they are
    the only thing that knows what a complete unit of work is; a dependency that
    commits on the way out would commit half-finished ones too.
    """
    factory = connection.app.state.session_factory
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
