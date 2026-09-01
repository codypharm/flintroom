"""a transcript line that is an earlier question, put again

#117. A tester asked a panelist to rephrase and a different panelist took the
floor, because every pattern the room knew meant *I did not hear you*. The
answer to *I did not understand you* is the same question in different words,
composed and said by the panelist who asked it.

That line has to be persisted — the presenter answers *those* words, and a
debrief ranking their answer against wording they never treated as final is
grading the wrong thing. And it has to be marked, or #56 happens again: a
rephrase and a fresh question are the same shape once written, so the original
would read as a question nobody even tried to answer, and the debrief would
tell somebody they ducked a question they had asked to have re-put.

Beside `disputed`, which exists for the same failure with a different cause.

`server_default="false"` rather than a backfill: every line written before this
migration was a first asking, so false is not a placeholder, it is the truth
about all of them. Nullable=False for the same reason — there is no line for
which the answer is unknown.

Revision ID: c7d1e4b93a20
Revises: a2a2f34208ec
Create Date: 2026-09-01 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d1e4b93a20'
down_revision: Union[str, Sequence[str], None] = 'a2a2f34208ec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "session_transcript_lines",
        sa.Column(
            "rephrasing",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("session_transcript_lines", "rephrasing")
