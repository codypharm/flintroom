"""auth identities

How a person signs in, and which `user_id` that resolves to. One row per
provider per person, so signing in with Apple and with Google produces two rows
pointing at one account.

`user_id` references `accounts.user_id` and is a plain UUID we mint. It is
deliberately not a foreign key into any auth provider's schema — `CLAUDE.md`
names that as the single decision separating a weekend migration from a
quarter-long one.

The email index is not incidental: it is read on every sign-in that finds no
matching identity, to decide whether this is a new person or a known one
arriving through another provider. Without it that becomes a sequential scan on
a table that only grows, on the path a user waits on.

Deny-all RLS, matching every other table (see 1f359ab487a7). This one holds
email addresses, which makes it the most directly personal table in the schema
and the one where the second wall is least theoretical.

Backwards-compatible: a new table with no existing readers.

Revision ID: 98d4de1877d3
Revises: 1f359ab487a7
Create Date: 2026-08-13 06:54:44.993054

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "98d4de1877d3"
down_revision: str | Sequence[str] | None = "1f359ab487a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "auth_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "email_verified", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["accounts.user_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "subject", name="uq_auth_identities_provider_subject"
        ),
    )
    op.create_index(
        "ix_auth_identities_email", "auth_identities", ["email"], unique=False
    )
    op.create_index(
        op.f("ix_auth_identities_user_id"),
        "auth_identities",
        ["user_id"],
        unique=False,
    )

    op.execute("ALTER TABLE auth_identities ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON auth_identities "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS deny_all ON auth_identities")
    op.drop_index(op.f("ix_auth_identities_user_id"), table_name="auth_identities")
    op.drop_index("ix_auth_identities_email", table_name="auth_identities")
    op.drop_table("auth_identities")
