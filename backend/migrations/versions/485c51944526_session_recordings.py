"""session recordings

That a room has audio, and whether it still does. The row outlives the object
it describes: it is the evidence a published retention window was honoured.

Revision ID: 485c51944526
Revises: a10c953111a3
Create Date: 2026-08-17 16:45:34.669211

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '485c51944526'
down_revision: Union[str, Sequence[str], None] = 'a10c953111a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('session_recordings',
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('byte_size', sa.Integer(), nullable=False),
    sa.Column('stored_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('session_id')
    )
    # The sweep's only predicate: rows not yet deleted. Every pass asks for
    # exactly this, and without it each one is a full scan of every recording
    # ever made — a table that only grows.
    op.create_index(
        "ix_session_recordings_deleted_at",
        "session_recordings",
        ["deleted_at"],
        unique=False,
    )

    # Defense in depth, deny-all and free of `auth.uid()` so it runs unchanged
    # on any Postgres (CLAUDE.md -> Database portability).
    op.execute("ALTER TABLE session_recordings ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON session_recordings "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_session_recordings_deleted_at'), table_name='session_recordings')
    op.execute("DROP POLICY IF EXISTS deny_all ON session_recordings")
    op.drop_index(
        "ix_session_recordings_deleted_at", table_name="session_recordings"
    )
    op.drop_table("session_recordings")
