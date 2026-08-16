"""The migration chain must describe the models exactly.

CLAUDE.md: every schema change is a new migration, and no manual DB edits. That
rule needs enforcement, not goodwill — a model edited without a migration passes
every other test in this suite right up until deploy.
"""

import ast
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.core.database import Base

MODULES = Path(__file__).resolve().parent.parent / "app" / "modules"
ENV = Path(__file__).resolve().parent.parent / "migrations" / "env.py"


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


def test_every_module_holding_a_table_is_imported_by_alembic():
    """The one failure the drift test above is structurally blind to.

    Autogenerate sees only what `migrations/env.py` has imported, and a module
    missing from it does not raise — it produces a migration that **drops** every
    table it could not see. `ingestion` and `voice` were both absent for several
    releases, and the only reason that surfaced as a crash rather than as a
    destructive migration is that `session_materials` happens to carry a foreign
    key into `materials`. A module without one would have gone quietly.

    The test above cannot catch this, and no amount of strengthening it would:
    it builds `Base.metadata` from the *test suite's* imports, where conftest
    pulls in every module. Its metadata is complete precisely when env.py's is
    not, which is why the gap survived every green run.

    So this reads env.py as text rather than importing it. That is unusual and it
    is the point — the invariant being asserted is a property of that file's
    import list, not of anything the process has already loaded. Importing it
    would defeat the test by loading the modules it is checking for.
    """
    declared = {
        path.parent.name
        for path in MODULES.glob("*/*.py")
        if "__tablename__" in path.read_text()
    }
    imported = {
        node.module.split(".")[2]
        for node in ast.walk(ast.parse(ENV.read_text()))
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("app.modules.")
    }

    assert declared <= imported, (
        "These modules declare tables that alembic cannot see, so "
        "`alembic revision --autogenerate` will emit a migration dropping them:\n"
        f"  {sorted(declared - imported)}\n"
        "Add each to the imports in migrations/env.py."
    )
