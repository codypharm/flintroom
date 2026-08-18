"""session difficulty level

The rung a room actually ran at — #55, `docs/difficulty-calibration.md`.

Distinct from `accounts.difficulty_level`, which is the rung a user is *on*. The
two diverge the moment calibration moves one, and without this nothing could
answer "which room did I get" about a session already finished.

Nullable with no default and no backfill, deliberately. Every existing session
predates the ladder, so there is no true value to write — and a plausible one
would be read by the debrief's comparison as a room that really happened at that
rung. Null means "no room was assembled", which is also the honest state for a
session started and never joined.

Revision ID: fd17209f748f
Revises: b6f8c92ec0c3
Create Date: 2026-08-18 14:02:19.447021

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fd17209f748f'
down_revision: Union[str, Sequence[str], None] = 'b6f8c92ec0c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "sessions", sa.Column("difficulty_level", sa.SmallInteger(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sessions", "difficulty_level")
