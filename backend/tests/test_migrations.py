"""The migration chain must describe the models exactly.

CLAUDE.md: every schema change is a new migration, and no manual DB edits. That
rule needs enforcement, not goodwill — a model edited without a migration passes
every other test in this suite right up until deploy.
"""

import ast
import os

from app.core.config import get_settings
from app.core.database import configured_url
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


def test_alembic_never_falls_back_to_a_database_written_in_this_file():
    """The trap that cost an afternoon on 2026-08-20.

    `env.py` read `DATABASE_URL` and defaulted to a hardcoded
    `...flintroom_test` when it was unset — which is the ordinary case at a
    terminal. So `alembic upgrade head` migrated the TEST database while
    appearing to migrate the one the app uses, `alembic current` reported the
    test database's revision while sounding like it reported the app's, and a
    new table existed everywhere except the database the phone talks to. The
    suite stayed green throughout, because the suite is the one caller that sets
    the variable on purpose.

    It is also the unfinished half of #28, "make .env actually configure the
    database": that fix moved `create_engine` off `os.getenv` and left this on
    it, with a fallback pointing somewhere else entirely.

    A URL in this file is the whole bug, so the guard is that there is not one.
    """
    source = ENV.read_text()

    assert "postgresql" not in source, (
        "migrations/env.py names a database. Unset DATABASE_URL and alembic "
        "will migrate whatever is written here rather than the app's own."
    )


def test_alembic_migrates_what_the_app_runs_on_when_nothing_says_otherwise(
    monkeypatch
):
    """No variable set means the app's database, never a guess.

    The test harness sets `DATABASE_URL` deliberately — that path is unchanged
    and is what keeps `pytest` on the test database. What changes is the
    default: it is now whatever `Settings` resolved from `.env`, so alembic and
    the application cannot disagree about which database they are looking at.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert configured_url() == get_settings().database_url


def test_an_explicit_variable_still_wins():
    """Deployment sets it, and the harness sets it. Both must be obeyed."""
    assert configured_url() == os.environ["DATABASE_URL"]
