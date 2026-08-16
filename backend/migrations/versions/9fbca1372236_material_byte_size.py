"""material byte size

The size the client declared, which is binding rather than advisory: it is
signed into the presigned PUT, so the object either has exactly this many bytes
or the store refused it. That is what makes the column safe to compare a tier
cap against without re-reading the object.

Added, rather than folded into `0d78b914fbba`, because that migration is already
committed. A migration that has left the branch is history and gets amended by a
successor, not by an edit — the alternative is two databases that ran "the same"
revision and disagree.

Filled with a server default and then stripped of it, in that order. NOT NULL on
a populated table needs a value for the existing rows; leaving the default in
place afterwards would let a future insert that forgets the size silently record
a zero-byte deck, which is a material that passes every cap and extracts to
nothing.

Backwards-compatible with the previously deployed version, which has no
`materials` table at all.

Revision ID: 9fbca1372236
Revises: 0d78b914fbba
Create Date: 2026-08-16 09:05:28.867745

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9fbca1372236"
down_revision: str | Sequence[str] | None = "0d78b914fbba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "materials",
        sa.Column("byte_size", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.alter_column("materials", "byte_size", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("materials", "byte_size")
