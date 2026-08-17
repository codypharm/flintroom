"""transcript line disputed

Whether a panel line opened by taking issue with a colleague's priorities — the
turn shape #54 added. Persisted because it is not derivable: once written, a
disputing line and an ordinary one are the same text by the same kind of speaker
in the same position, and only the room knew the difference.

The debrief reads it to separate a question a colleague talked over from one the
presenter ducked. Both are unanswered; one is the user's fault.

Backwards-compatible: NOT NULL with a false default, so rooms recorded before
this migration read as undisputed — which they were, since every line predating
#54 was addressed to the presenter.

Revision ID: 8ae7db9265f9
Revises: cfad433cf9c1
Create Date: 2026-08-17 22:24:29.175341

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8ae7db9265f9'
down_revision: Union[str, Sequence[str], None] = 'cfad433cf9c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "session_transcript_lines",
        sa.Column(
            "disputed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("session_transcript_lines", "disputed")
