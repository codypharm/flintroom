"""account deletion requested at

When somebody asked for their account to be deleted, or null. Apple has required
in-app deletion since 2022, so this is a store blocker rather than a courtesy.

Two timestamps: when somebody asked, and when the purge ran. The request stays
true afterwards, and the sweep needs to tell an account it has already emptied
from one whose window has just closed — without that it re-purges every pass and
the swept count stops being usable as an alerting signal.

A timestamp rather than a state, matching sessions.grace_started_at: nothing
about how the account behaves during the window changes, so a state would double
the table for no behavioural difference. Indexed because the sweep selects on it
every pass and almost every row is null.

Revision ID: 8afbd2d49140
Revises: c281a96569c3
Create Date: 2026-08-18 11:40:25.723568

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8afbd2d49140'
down_revision: Union[str, Sequence[str], None] = 'c281a96569c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "accounts",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "accounts",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_accounts_deletion_requested_at",
        "accounts",
        ["deletion_requested_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_accounts_deletion_requested_at", table_name="accounts")
    op.drop_column("accounts", "deleted_at")
    op.drop_column("accounts", "deletion_requested_at")
