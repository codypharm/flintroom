"""when this room's reading included strengths — the score's birth certificate

#118. A room debriefed before strengths existed was read by a model that was
never asked what held. Its strong-answer count is zero rows, which is exactly
what a room where nothing held also looks like — and the difference matters,
because one has a score of nothing-held and the other has no score at all.
Showing the first as the second tells a tester they held 0 of 6 in a room
that was never judged that way.

A timestamp rather than a boolean for the reason `debriefed_at` is one: "when"
answers "whether" for free, and the reverse is not true.

No backfill, and NULL is the truth about every existing row: no room read
before this migration was scored.

Revision ID: f3b9c1e57a28
Revises: e8f2a6c40d17
Create Date: 2026-09-01 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3b9c1e57a28'
down_revision: Union[str, Sequence[str], None] = 'e8f2a6c40d17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "scored_at")
