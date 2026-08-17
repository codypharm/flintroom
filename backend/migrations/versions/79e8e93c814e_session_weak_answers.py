"""session weak answers

Product.md §3.5's ranked weak-answer list, made durable. Written when a debrief
first opens — not at settlement, which has four callers and is the billing-close
path — and read afterwards by the coach, the prep sheet and #55's calibration.

Keyed on (session_id, rank) rather than a surrogate id: the pair is the fact,
and a retry that wrote the list again conflicts rather than duplicating. The
rank is the model's own ordering and is stored rather than derived, because it
moves between runs on the same transcript.

Revision ID: 79e8e93c814e
Revises: 5a4e9c7c21ff
Create Date: 2026-08-17 23:37:44.996038

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '79e8e93c814e'
down_revision: Union[str, Sequence[str], None] = '5a4e9c7c21ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "session_weak_answers",
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("asked_by", sa.String(length=64), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("weakness", sa.String(length=32), nullable=False),
        sa.Column("why", sa.Text(), nullable=False),
        sa.Column(
            "found_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id", "rank", name="pk_session_weak_answers"),
    )

    # Defense in depth, deny-all and free of `auth.uid()` so it runs unchanged
    # on any Postgres (CLAUDE.md -> Database portability).
    op.execute("ALTER TABLE session_weak_answers ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON session_weak_answers "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS deny_all ON session_weak_answers")
    op.drop_table("session_weak_answers")
