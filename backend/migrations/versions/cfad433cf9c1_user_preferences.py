"""user preferences

What an account has chosen, where the choice is not money. A row exists only
once somebody has chosen something — every default lives in the model.

Revision ID: cfad433cf9c1
Revises: 485c51944526
Create Date: 2026-08-17 17:27:41.392317

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cfad433cf9c1'
down_revision: Union[str, Sequence[str], None] = '485c51944526'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('user_preferences',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('records_rooms', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('user_id')
    )

    # Defense in depth, deny-all and free of `auth.uid()` so it runs unchanged
    # on any Postgres (CLAUDE.md -> Database portability).
    op.execute("ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON user_preferences "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS deny_all ON user_preferences")
    op.drop_table("user_preferences")
