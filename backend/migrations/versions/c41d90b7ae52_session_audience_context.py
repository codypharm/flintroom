"""sessions.audience — what the presenter says about the room they are facing

Revision ID: c41d90b7ae52
Revises: b3c7e1f42d08
Create Date: 2026-08-21

#66, and `Product.md` §3.1's permitted substitute for the social-profile
scraping the project refused: *"the user may paste their own text describing the
audience ... User-supplied, not app-scraped."*

Nullable and with no default, so this is backwards-compatible in both
directions: the previously deployed build inserts sessions without naming the
column and gets a null, which is exactly what "nobody described the room" means.
Nothing has to be backfilled, because every room that already ran was run
without one.

`Text` rather than `String(400)`. The cap is `AUDIENCE_LIMIT`, and it is part of
the *fencing* rather than a storage concern — it is enforced at the schema, at
422, where the user can be told. A column-level limit would add a second
authority free to disagree with the first, and the one that lost would surface
as a 500 on somebody's Start tap.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c41d90b7ae52'
down_revision: Union[str, Sequence[str], None] = 'b3c7e1f42d08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("sessions", sa.Column("audience", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema.

    Drops user-written text. Reversible only in the schema sense — the notes
    themselves are gone, and a room re-run after this has nothing to prefill.
    """
    op.drop_column("sessions", "audience")
