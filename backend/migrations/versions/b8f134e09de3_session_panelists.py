"""session panelists

Who was in a room, fixed when the room opened.

Revision ID: b8f134e09de3
Revises: b3c9d1e57a24
Create Date: 2026-08-16 18:16:41.201189

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8f134e09de3'
down_revision: Union[str, Sequence[str], None] = 'b3c9d1e57a24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "session_panelists",
        sa.Column("session_id", sa.UUID(), nullable=False),
        # The archetype's key into `app/agents/archetypes.py`, not a snapshot of
        # its persona — see the model for why, and for what changes when Pro
        # users start authoring their own.
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("seat", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id", "name", name="pk_session_panelists"),
    )
    op.create_index(
        "uq_session_panelists_seat",
        "session_panelists",
        ["session_id", "seat"],
        unique=True,
    )

    # Defense in depth, deny-all and free of `auth.uid()` so it runs unchanged on
    # any Postgres (CLAUDE.md → Database portability). The real wall is that all
    # access goes through FastAPI on the service role.
    op.execute("ALTER TABLE session_panelists ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON session_panelists "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS deny_all ON session_panelists")
    op.drop_index("uq_session_panelists_seat", table_name="session_panelists")
    op.drop_table("session_panelists")
