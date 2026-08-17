"""session transcript lines

What was said in a room, both sides, kept after the room ends.

The first content this product retains — everything before it was money, proof
or telemetry. See `docs/session-retention.md` for what that obliges.

Revision ID: a10c953111a3
Revises: b8f134e09de3
Create Date: 2026-08-17 15:08:01.684940

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a10c953111a3'
down_revision: Union[str, Sequence[str], None] = 'b8f134e09de3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "session_transcript_lines",
        sa.Column("session_id", sa.UUID(), nullable=False),
        # Where the line falls in the room, from zero. Explicit rather than
        # inferred from `said_at`: lines are written as they are said, so two can
        # share a clock reading — and a transcript that occasionally transposes a
        # question and its answer is worse than one that never loads, because
        # nothing about it looks wrong.
        sa.Column("ordinal", sa.Integer(), nullable=False),
        # `user`, or an archetype's name. Deliberately not a foreign key to
        # `session_panelists`: a transcript records what was said, and must stay
        # readable if the roster it was said by is ever reshaped.
        sa.Column("speaker", sa.String(length=64), nullable=False),
        # Unbounded, because an utterance is. A length cap here would mean a user
        # who talked for ninety seconds without pausing silently lost the end of
        # their own sentence.
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "said_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Cascade because a line has no meaning without its room — and because
        # deleting the session is how a transcript is disposed of when an account
        # goes.
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        # The pair is the fact, as with `session_materials`. A surrogate id would
        # leave "the fourth thing said" expressible twice, and make a retried
        # write a duplicate rather than a no-op.
        sa.PrimaryKeyConstraint(
            "session_id", "ordinal", name="pk_session_transcript_lines"
        ),
    )

    # Defense in depth, deny-all and free of `auth.uid()` so it runs unchanged on
    # any Postgres (CLAUDE.md → Database portability). The real wall is that all
    # access goes through FastAPI on the service role.
    #
    # It matters more here than on the tables either side of it. Every other row
    # this product stores is a number about a user; these are a user's own words,
    # and the one table where a policy gap is a disclosure rather than a leak of
    # accounting.
    op.execute("ALTER TABLE session_transcript_lines ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON session_transcript_lines "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS deny_all ON session_transcript_lines")
    op.drop_table("session_transcript_lines")
