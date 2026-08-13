"""rate limit counters

One row per key per window. Postgres rather than Redis, per the decision
recorded in docs/deferred-scale-work.md: only the auth and session-start
endpoints are limited, and this product's concurrency is bounded by provider
cost long before a counter table is.

The composite primary key is what makes the increment atomic — the upsert
conflicts on it, so concurrent requests serialise on one row instead of each
reading the same count and each deciding it is under the limit.

Rows are disposable. Losing the table costs a moment of unlimited attempts and
nothing a user owns, which is also why the sweep that clears old windows can be
blunt.

Deny-all RLS, as every table (see 1f359ab487a7).

Backwards-compatible: a new table with no existing readers.

Revision ID: 3a948f56c1ed
Revises: ca57fc4a0754
Create Date: 2026-08-13 07:10:15.705753

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3a948f56c1ed'
down_revision: Union[str, Sequence[str], None] = 'ca57fc4a0754'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('rate_limit_counters',
    sa.Column('bucket_key', sa.String(length=160), nullable=False),
    sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('count', sa.Integer(), server_default='0', nullable=False),
    sa.PrimaryKeyConstraint('bucket_key', 'window_start')
    )

    op.execute("ALTER TABLE rate_limit_counters ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON rate_limit_counters "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS deny_all ON rate_limit_counters")
    op.drop_table('rate_limit_counters')
