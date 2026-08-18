"""session coach turns

The coaching conversation, kept so it survives a phone backgrounding mid-debrief.

Separate from session_transcript_lines, which is the room. One table would put
the coach's own words inside the record it is grounded in and cites from, so a
conversation would gradually become its own evidence.

Server-side rather than carried by the client: a history the client supplied
would be a history the client could edit, and the model reads it as context.

Revision ID: fc9ff7c4f86e
Revises: 79e8e93c814e
Create Date: 2026-08-18 09:07:03.276559

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fc9ff7c4f86e'
down_revision: Union[str, Sequence[str], None] = '79e8e93c814e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "session_coach_turns",
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("who", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "said_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id", "ordinal", name="pk_session_coach_turns"),
    )

    # Defense in depth, deny-all and free of `auth.uid()` so it runs unchanged
    # on any Postgres (CLAUDE.md -> Database portability).
    op.execute("ALTER TABLE session_coach_turns ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON session_coach_turns "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS deny_all ON session_coach_turns")
    op.drop_table("session_coach_turns")
