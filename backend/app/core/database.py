import os

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, cast

from starlette.requests import HTTPConnection
from sqlalchemy import CursorResult, Result, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for every Flintroom ORM model."""


def configured_url() -> str:
    """Which database this process should talk to.

    `DATABASE_URL` first, because deployment sets it and `tests/conftest.py`
    sets it on purpose — that is what keeps `pytest` on the test database while
    still exercising the real migration chain.

    **Otherwise the application\'s own, and never a name written in a file.**
    `migrations/env.py` used to fall back to a hardcoded `...flintroom_test`,
    which meant that at an ordinary terminal — where nobody exports the
    variable — `alembic upgrade head` migrated the test database while
    appearing to migrate the app\'s, and `alembic current` reported the test
    database\'s revision in the same voice. On 2026-08-20 a table was created
    everywhere except the database the phone talks to, and the suite stayed
    green throughout, because the suite is the one caller that sets the
    variable.

    It was the unfinished half of #28, "make .env actually configure the
    database": that fix moved `create_engine` off `os.getenv` and left the
    migrations on it, pointed somewhere else.

    Here rather than in `env.py` so it can be imported and tested — that file
    reads `context.config` at module scope and cannot be imported outside an
    alembic run, which is exactly how a resolver nobody could test came to have
    a fallback nobody noticed.
    """
    return os.getenv("DATABASE_URL") or get_settings().database_url


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


async def get_session_factory(
    connection: HTTPConnection,
) -> async_sessionmaker[AsyncSession]:
    """The factory itself, for the few callers that need a session of their own.

    `get_db` hands out one session bound to the request, which is right for
    almost everything. The exception is work that runs on a task *beside* the
    request rather than inside it — a live room writes its transcript from the
    channel's listener while the relay writes progress from the loop consuming
    it, and one `AsyncSession` cannot be flushed from two tasks at once.

    A dependency rather than a reach through `websocket.app`, so that a caller
    can be handed one in a test without inventing an application to hang it off.
    """
    return connection.app.state.session_factory


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

    `scalar` is typed as nullable because most queries can select nothing.
    `SELECT transaction_timestamp()` is not one of them — it has no `FROM` and
    always produces exactly one row — so the null is a shape the database cannot
    return, and asserting it is more honest than a caller-side `or datetime.now`
    that would quietly reintroduce the second clock this exists to avoid.
    """
    now = await db.scalar(select(func.now()))
    assert now is not None
    return now


def rows_touched(result: Result[Any]) -> int:
    """How many rows a DML statement actually changed.

    **A library-stub gap, cast once and named, rather than seven suppressions.**
    `AsyncSession.execute` is typed as returning `Result`, which has no
    `rowcount`; every `UPDATE` and `DELETE` really returns a `CursorResult`,
    which does. Casting at each call site would scatter the same claim through
    four modules, and a bare ignore comment outlives the thing it suppressed.

    Worth a name of its own because every caller is doing the same load-bearing
    thing: `rowcount` is how this codebase makes a conditional write tell it
    whether it won. `DebriefService` claims a room with it, `RefreshService`
    retires a token with it, and the rate limiter decides a request on it — each
    one a race that the database, not the application, arbitrates.
    """
    return cast("CursorResult[Any]", result).rowcount


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Sessions for work that has no request behind it.

    `expire_on_commit` off for the reason the sweeps document at length: a
    commit or rollback that expires mapped objects makes the next attribute read
    a lazy database call, which in async code surfaces as `MissingGreenlet`
    rather than as anything resembling its cause.
    """
    return async_sessionmaker(engine, expire_on_commit=False)
