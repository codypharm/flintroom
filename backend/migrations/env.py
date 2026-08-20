import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    # disable_existing_loggers defaults to True, which silences every logger
    # already created — including the application's, since modules build theirs
    # at import time. Running migrations in-process would otherwise turn off
    # application logging for the life of the process.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

from app.core.database import Base

# Importing the models registers them on Base.metadata. Autogenerate only sees
# what has been imported, and a module missing here does not fail — it produces
# a migration that *drops* whatever it could not see. `ingestion` and `voice`
# were both absent for several releases, which is why every table in them was
# created by a hand-written migration: autogenerate could not run at all once
# `session_materials` grew a foreign key into a table it had never imported.
#
# The drift guard in tests/test_migrations.py did not catch it. That test builds
# `Base.metadata` from the test suite's own imports, where conftest pulls in
# every module — so the metadata it compares is complete even when this file's
# is not. Nothing except running the CLI reveals the gap. Add the module here
# when you add a module with a table in it.
from app.modules.audit_log import models as audit_log_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.billing import models as billing_models  # noqa: F401
from app.modules.ingestion import models as ingestion_models  # noqa: F401
from app.modules.onboarding import models as onboarding_models  # noqa: F401
from app.modules.panels import models as panels_models  # noqa: F401
from app.modules.sessions import models as sessions_models  # noqa: F401
from app.modules.voice import costs as voice_costs  # noqa: F401
from app.modules.voice import models as voice_models  # noqa: F401

target_metadata = Base.metadata

# The URL comes from the environment, never from alembic.ini — CLAUDE.md allows
# zero secrets in code, and the production URL is a secret.
config.set_main_option(
    "sqlalchemy.url",
    os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://flintroom:flintroom@localhost:55432/flintroom_test",
    ),
)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
