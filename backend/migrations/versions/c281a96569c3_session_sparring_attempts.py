"""session sparring attempts

§3.5's re-try loop, kept. Anchored to a weak answer by rank rather than
free-floating: a sparring turn is fresh speech, and the anchor is what stops
"spar me on this instead" from being a way to smuggle in a new pitch. Only a row
that already exists is addressable.

Keyed on (session_id, weak_rank, attempt). The count is content — §3.5 says
"repeatedly", and #55 reads how many goes a question took.

Revision ID: c281a96569c3
Revises: fc9ff7c4f86e
Create Date: 2026-08-18 09:47:14.484488

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c281a96569c3'
down_revision: Union[str, Sequence[str], None] = 'fc9ff7c4f86e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "session_sparring_attempts",
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("weak_rank", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("said", sa.Text(), nullable=False),
        sa.Column("reply", sa.Text(), nullable=False),
        sa.Column(
            "said_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "session_id", "weak_rank", "attempt", name="pk_session_sparring_attempts"
        ),
    )

    op.execute("ALTER TABLE session_sparring_attempts ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON session_sparring_attempts "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS deny_all ON session_sparring_attempts")
    op.drop_table("session_sparring_attempts")
