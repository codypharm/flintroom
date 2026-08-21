"""session_costs index for the daily spend ceiling

Revision ID: b3c7e1f42d08
Revises: a29a4e694446
Create Date: 2026-08-21

The ceiling asks one question at every session start: what has this account cost
us in the last twenty-four hours. Without this index that is a scan of every
cost row ever written, on the one path where latency is the product.

Additive and backwards-compatible: an index is invisible to the previous
deployment, so this can go out ahead of the code that needs it.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b3c7e1f42d08'
down_revision: Union[str, Sequence[str], None] = 'a29a4e694446'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # `user_id` first because it is the equality and `recorded_at` the range —
    # the other order would make the leading column useless for the lookup.
    op.create_index(
        "ix_session_costs_user_recorded",
        "session_costs",
        ["user_id", "recorded_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_session_costs_user_recorded", table_name="session_costs")
