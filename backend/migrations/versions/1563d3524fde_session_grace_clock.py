"""session grace clock

When a session started running past a zero balance, or null if it is not.
Nullable and unbacked by a default, so the previously deployed version keeps
inserting sessions unchanged — to it, every session is simply not in grace,
which was already true.

Revision ID: 1563d3524fde
Revises: 40e2bbd39eae
Create Date: 2026-08-12 18:44:13.055683

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1563d3524fde'
down_revision: Union[str, Sequence[str], None] = '40e2bbd39eae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("grace_started_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "grace_started_at")
