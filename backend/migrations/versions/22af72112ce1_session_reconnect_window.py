"""session reconnect window

The two columns the reconnect window stands on — #100, `docs/reconnect.md`.

`disconnected_at` is the stamp a room carries while its presenter might come
back: set by the relay on an abnormal socket close, cleared on resume, and
read by exactly one judge — the reaper, which settles the room as
`client_disconnect` once the stamp is older than the window. Deliberately a
timestamp on a still-`active` session rather than a sixth state, so every
query that means "this user has a live room" — above all the one-live-session
lock — stays correct untouched.

`connection_id` is the nonce that says which socket currently speaks for the
room. Each accepted connection writes its own; the disconnect stamp is written
only by the connection that still holds it. Without this, a half-open socket's
delayed death would stamp a room its owner had already resumed — stopping its
billing and starting its reaper clock while the presenter is mid-answer.
Database-enforced rather than in-process, so it holds across replicas.

Both nullable with no backfill: every existing session predates the window,
and every settled one is past caring.

Revision ID: 22af72112ce1
Revises: d84f1c2b93a7
Create Date: 2026-08-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = '22af72112ce1'
down_revision: Union[str, Sequence[str], None] = 'd84f1c2b93a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "sessions",
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sessions", sa.Column("connection_id", UUID(as_uuid=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sessions", "connection_id")
    op.drop_column("sessions", "disconnected_at")
