"""session last user speech

When the user last said something, or null if they never have. Nullable and
without a default, so the previously deployed version keeps inserting sessions
unchanged — to it every session has simply never had speech recorded, which was
already true.

Revision ID: 9b3623e0fcdd
Revises: 1563d3524fde
Create Date: 2026-08-12 21:13:22.918737

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b3623e0fcdd'
down_revision: Union[str, Sequence[str], None] = '1563d3524fde'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("last_user_speech_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "last_user_speech_at")
