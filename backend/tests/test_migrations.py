"""The migration chain must describe the models exactly.

CLAUDE.md: every schema change is a new migration, and no manual DB edits. That
rule needs enforcement, not goodwill — a model edited without a migration passes
every other test in this suite right up until deploy.
"""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.core.database import Base


async def test_models_and_migrations_have_not_drifted(engine):
    """Autogenerate against the migrated schema must find nothing to do."""

    def diff(sync_connection):
        context = MigrationContext.configure(sync_connection)
        return compare_metadata(context, Base.metadata)

    async with engine.connect() as connection:
        differences = await connection.run_sync(diff)

    assert differences == [], (
        "Models and migrations disagree. Generate a migration:\n"
        "  PYTHONPATH=. uv run alembic revision --autogenerate -m '<what changed>'\n"
        f"Outstanding: {differences}"
    )
