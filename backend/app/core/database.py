import os

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


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Sessions for work that has no request behind it.

    `expire_on_commit` off for the reason the sweeps document at length: a
    commit or rollback that expires mapped objects makes the next attribute read
    a lazy database call, which in async code surfaces as `MissingGreenlet`
    rather than as anything resembling its cause.
    """
    return async_sessionmaker(engine, expire_on_commit=False)
