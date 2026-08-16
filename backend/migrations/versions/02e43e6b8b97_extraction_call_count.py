"""extraction call count

How many model calls it took to read one material.

A full pro-tier deck is around 600k input tokens and does not fit in any
context window in one piece, so it is read in chunks of twenty pages (task
#31). Per-call overhead is repeated instruction tokens, and `input_tokens`
alone cannot be separated into pages versus overhead — this column is what
makes that separable, and what says whether the chunk size is set anywhere near
right once real decks have run through it.

`server_default='1'` rather than nullable: every row written before this
migration was a single call, so one is the true value for them rather than a
placeholder. The default is then dropped, so the application supplies the number
and a future writer cannot silently record a fifteen-call extraction as one.

Backwards-compatible with the previously deployed version: a new column with a
default, so an older API writing this table continues to work.

Revision ID: 02e43e6b8b97
Revises: f5d995026695
Create Date: 2026-08-16 12:03:44.918204

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "02e43e6b8b97"
down_revision: str | Sequence[str] | None = "f5d995026695"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "extraction_costs",
        sa.Column("calls", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("extraction_costs", "calls")
