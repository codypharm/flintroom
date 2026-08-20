"""custom archetypes

Panelists a user wrote, stored as rows rather than shipped as config (#65).
`docs/custom-archetypes.md` is the resolved design; this is only its storage,
and two of its decisions are visible here as constraints.

The primary key is the NAME, not a separate id. `session_panelists` stores a
name, and every lookup arrives with one — a second identifier would be a second
thing to keep in step. The check constraint forces the `custom:` prefix, which
is what keeps this table and `agents/archetypes.LIBRARY` from ever writing into
one namespace: `by_name()` refuses anything carrying the prefix, so a row can
never shadow a shipped archetype the way `retention` shadowed the Risk Officer's
`data` domain.

`archived_at` is what "delete" sets. Rooms are kept for the life of the account
and render who was in them, so a destroyed panelist would leave a dangling name
in every transcript that used it. The unique index on title is partial on
`archived_at IS NULL` for the same reason from the other side: a title has to be
reusable once its holder is retired, and the retired row has to keep its own.

No foreign key on `user_id`. A plain UUID, never a reference to `auth.users` —
CLAUDE.md → Database portability. Which is exactly why this table joined
`billing/deletion.PURGED` in the same change: nothing cascades from a user by
design, so a table left out of that path is personal data retained forever with
nothing raising.

Revision ID: b7e41c093a55
Revises: a3c17b90e5d2
Create Date: 2026-08-20 14:22:08.117204

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b7e41c093a55'
down_revision: Union[str, Sequence[str], None] = 'a3c17b90e5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "custom_archetypes",
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("persona", sa.Text(), nullable=False),
        sa.Column(
            "domains",
            postgresql.ARRAY(sa.String(length=32)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("voice", sa.String(length=32), nullable=True),
        sa.Column("supersedes", sa.String(length=80), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("name"),
        sa.CheckConstraint("name LIKE 'custom:%'", name="ck_custom_archetypes_name"),
        # SET NULL rather than CASCADE: a superseded row being purged must not
        # take its replacement with it, which is the row a live room is using.
        sa.ForeignKeyConstraint(
            ["supersedes"], ["custom_archetypes.name"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "uq_custom_archetypes_title",
        "custom_archetypes",
        ["user_id", "title"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index(
        "ix_custom_archetypes_live",
        "custom_archetypes",
        ["user_id", "created_at"],
        postgresql_where=sa.text("archived_at IS NULL"),
    )

    op.execute("ALTER TABLE custom_archetypes ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON custom_archetypes "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS deny_all ON custom_archetypes")
    op.drop_index("ix_custom_archetypes_live", table_name="custom_archetypes")
    op.drop_index("uq_custom_archetypes_title", table_name="custom_archetypes")
    op.drop_table("custom_archetypes")
