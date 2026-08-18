"""session debriefed at

When a room's weak answers were read — the "already read" mark.

**Fixes a defect in #57 rather than adding a feature.** `DebriefService` decided
a room had been read by whether any `session_weak_answers` rows came back, and a
room the model found nothing wrong with produces none — indistinguishable from
one nobody has opened. Every open of a flawless debrief therefore bought a fresh
reasoning-model pass over the whole transcript, on the phase §4.1 promises is
unmetered. It is also the race guard now, which the primary key on
`(session_id, rank)` could not be for an empty list.

Backfilled for rooms that already have weak answers stored, because those *were*
read and re-reading them would cost exactly what this exists to stop. A settled
room with no rows is left null: it may genuinely never have been opened, and the
worse error is marking a room read that nobody has read — that one hides a
debrief from a user, where the other spends one model call.

Revision ID: b6f8c92ec0c3
Revises: 792f04e76bea
Create Date: 2026-08-18 13:34:02.881451

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6f8c92ec0c3'
down_revision: Union[str, Sequence[str], None] = '792f04e76bea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "sessions",
        sa.Column("debriefed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE sessions
           SET debriefed_at = settled_at
         WHERE settled_at IS NOT NULL
           AND EXISTS (
                 SELECT 1
                   FROM session_weak_answers
                  WHERE session_weak_answers.session_id = sessions.id
               )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sessions", "debriefed_at")
