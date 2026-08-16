"""extraction retry backoff

What lets a rate-limited deck wait instead of dying.

Under load the extraction adapter's retries exhaust unevenly — some chunks land,
some do not — so a partial failure is the *likely* shape of a rate-limit event
rather than a rare one. Without somewhere to record a wait, the only endings
available were `ready` and `failed`, and `failed` is terminal: a busy minute
would have told users to re-upload decks that were never the problem.

`retry_at` puts the backoff in the queue rather than in a sleeping worker. The
worker that would sleep is the one every other deck is waiting on.

`attempts` counts only retryable endings. A deck the API refuses outright fails
on the first attempt — retrying produces the same refusal — so it needs no
budget. The budget here exists only so a pathological deck cannot be claimed
forever.

`ix_materials_extractable` is rebuilt with `retry_at` ahead of `created_at`,
because the claim query filters on it before it orders by anything. Scanning
past every backed-off material to find the next candidate is what would make one
rate-limit event slow down the decks that are fine.

Backwards-compatible with the previously deployed version: both columns have
defaults, and the index change is transparent to any query. An older API neither
writes nor reads them, which leaves every material eligible immediately — the
behaviour it already had.

Revision ID: 2da199d1c1bb
Revises: 02e43e6b8b97
Create Date: 2026-08-16 13:22:51.660417

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2da199d1c1bb"
down_revision: str | Sequence[str] | None = "02e43e6b8b97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXTRACTABLE = sa.text("state IN ('pending', 'extracting')")


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "materials", sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "materials",
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
    )

    op.drop_index("ix_materials_extractable", table_name="materials")
    op.create_index(
        "ix_materials_extractable",
        "materials",
        ["state", "retry_at", "created_at"],
        postgresql_where=EXTRACTABLE,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_materials_extractable", table_name="materials")
    op.create_index(
        "ix_materials_extractable",
        "materials",
        ["state", "created_at"],
        postgresql_where=EXTRACTABLE,
    )

    op.drop_column("materials", "attempts")
    op.drop_column("materials", "retry_at")
