"""deny all row level security

Defense-in-depth, not the primary boundary. FastAPI holds the only credential
the application uses and that role owns these tables, so it bypasses RLS and
nothing about the running system changes. What this closes is the path that does
not go through FastAPI at all: a leaked key, PostgREST, an analytics role granted
more than intended.

Deny-all with no `auth.uid()`, per CLAUDE.md. Policies free of Supabase auth
helpers run unchanged on RDS or Cloud SQL, which is the property that keeps the
exit from Supabase a `pg_dump` rather than a rewrite.

The explicit policy is redundant against Postgres semantics — a table with RLS
enabled and no policy already denies everyone. It is written anyway so that the
intent is visible in `pg_policies`: an empty policy list reads as an oversight,
and the next person to look would reasonably wonder whether one was dropped.

Backwards-compatible with the previously deployed version: the application role
is unaffected, so an older API talking to this schema behaves identically.

Revision ID: 1f359ab487a7
Revises: 9b3623e0fcdd
Create Date: 2026-08-12 22:09:51.809342

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1f359ab487a7"
down_revision: str | Sequence[str] | None = "9b3623e0fcdd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Every table the application owns. `alembic_version` is deliberately absent —
#: it belongs to Alembic, carries no user data, and locking it would complicate
#: migrations for no gain.
#:
#: This list is checked against the model metadata by a test rather than trusted
#: here, so a table added later without a policy fails the suite.
TABLES = (
    "accounts",
    "ledger_entries",
    "sessions",
    "session_phase_spans",
    "audit_events",
)


def upgrade() -> None:
    """Upgrade schema."""
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY deny_all ON {table} "
            "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS deny_all ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
