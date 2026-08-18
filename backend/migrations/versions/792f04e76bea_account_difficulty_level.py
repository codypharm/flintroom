"""account difficulty level

How hard the room pushes one person — #55, `docs/difficulty-calibration.md`.

Backwards-compatible with the version deployed before it, which `CLAUDE.md`
requires of every migration: the column is nullable-free only because it carries
a server default, so a running instance that has never heard of it keeps
inserting accounts successfully and every row it writes lands on the gentle
rung.

**Every existing account lands on level 1 as well**, and that is the intended
reading rather than an accident of the default. Nothing was calibrated before
this ran, so no row has earned a harder room; starting everyone at the floor
errs toward Open Risk #1 rather than away from it, and one good session moves
them up.

Revision ID: 792f04e76bea
Revises: 8afbd2d49140
Create Date: 2026-08-18 13:12:41.130117

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '792f04e76bea'
down_revision: Union[str, Sequence[str], None] = '8afbd2d49140'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "accounts",
        sa.Column(
            "difficulty_level",
            sa.SmallInteger(),
            nullable=False,
            # Written out rather than interpolated from `difficulty.GENTLE`. A
            # migration is a record of what was done to a database on a date,
            # and one that imports application code describes whatever that code
            # says today rather than what it said when this ran.
            server_default="1",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("accounts", "difficulty_level")
