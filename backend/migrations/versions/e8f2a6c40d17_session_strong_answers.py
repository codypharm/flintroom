"""the other half of the debrief — the answers that held

#118. Testers asked for a rating; the architect chose a score counted in code
from verified findings, and the count needs a numerator: the answers that
held, judged in the same reading as the weak ones and written in the same
transaction, on the same first debrief open.

Keyed on (session_id, ordinal) rather than rank, because strengths are
unranked — the score counts them, and a count has no order. One row per
question is the fact: `verified_strengths` dedupes on ordinal upstream, and
the key holds the line if that ever drifts.

`answer` is NOT NULL where the weak table's is nullable. A weak answer may be
silence; an answer that held cannot be, and a row claiming otherwise is a
bug better refused by the database than stored.

No backfill. Rooms debriefed before this migration were read by a model that
was never asked what held, so there is nothing true to write — their score
simply does not exist, which the API represents rather than invents.

Revision ID: e8f2a6c40d17
Revises: c7d1e4b93a20
Create Date: 2026-09-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID


# revision identifiers, used by Alembic.
revision: str = 'e8f2a6c40d17'
down_revision: Union[str, Sequence[str], None] = 'c7d1e4b93a20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "session_strong_answers",
        sa.Column("session_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("asked_by", sa.String(64), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("strength", sa.String(32), nullable=False),
        sa.Column("why", sa.Text(), nullable=False),
        sa.Column(
            "found_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "session_id", "ordinal", name="pk_session_strong_answers"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], ondelete="CASCADE"
        ),
    )

    # Deny-all RLS, like every other table: service-role access through the
    # API is the wall, and a policy free of auth helpers runs on any Postgres.
    op.execute("ALTER TABLE session_strong_answers ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON session_strong_answers "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    op.drop_table("session_strong_answers")
