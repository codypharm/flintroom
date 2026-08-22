"""session_transcript_lines.began_at_seconds — where a line falls in the recording

Revision ID: d84f1c2b93a7
Revises: c41d90b7ae52
Create Date: 2026-08-22

#69. `ordinal` says where a line falls in the *conversation* and stays the only
ordering key; nothing here touches that reasoning. This adds a separate,
non-ordering fact: how many seconds into the room the line began, so a finding
can point at the moment it happened rather than at a file starting from zero.

**A position in the mixed recording, not a wall clock.** Read from
`RoomMixer.elapsed`, whose count of user samples *is* the object a player scrubs
— `said_at` already records when a row was written, which is close to when the
words were said and not the same thing, and "close" is the whole difference
between a reading aid and a seek.

Nullable, with no default and no backfill, which makes this backwards-compatible
in both directions: the previously deployed build inserts lines without naming
the column and gets a null, and every room that already ran genuinely has no
offset. **Backfilling would be worse than leaving it empty** — an invented one
is not a gap in the record, it is a player seeking confidently to the wrong
place, and nothing about that looks wrong.

`Float` rather than `Numeric`. This is a duration read off a sample count and
consumed as a seek; nothing compares two of them for equality and nothing sums
them into money, which are the two reasons the rest of this schema reaches for
exact decimals.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd84f1c2b93a7'
down_revision: Union[str, Sequence[str], None] = 'c41d90b7ae52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "session_transcript_lines",
        sa.Column("began_at_seconds", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema.

    Loses every offset. The transcript and the recording both survive intact —
    what goes is the ability to line one up against the other, and it cannot be
    recomputed afterwards: the mixer that knew is gone with the room.
    """
    op.drop_column("session_transcript_lines", "began_at_seconds")
