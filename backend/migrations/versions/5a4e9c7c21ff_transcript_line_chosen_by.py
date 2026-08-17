"""transcript line chosen_by

What handed a panelist the floor — `finding`, `model` or `fallback`. Null for
the user's own lines, which nobody chose.

`chosen_by = 'finding'` is the only record that outlives the room of the Auditor
having caught a contradiction: a Finding is read from one utterance, routes the
next turn, and is discarded. The debrief ranks a contradiction above a
panelist's dissatisfaction, so it has to be able to tell them apart.

Plain text, not a Postgres enum. `SelectedBy` is a routing vocabulary that may
grow a fourth path, and adding a value to an enum type is a migration that locks
a table live rooms are writing to.

Backwards-compatible: nullable with no default, so rooms recorded before this
read as "unknown" rather than falsely claiming the selection model spoke.

Revision ID: 5a4e9c7c21ff
Revises: 8ae7db9265f9
Create Date: 2026-08-17 22:39:18.639222

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5a4e9c7c21ff'
down_revision: Union[str, Sequence[str], None] = '8ae7db9265f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "session_transcript_lines",
        sa.Column("chosen_by", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("session_transcript_lines", "chosen_by")
