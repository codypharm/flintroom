"""app events

First-party analytics — #105, the architect's choice over a vendor SDK. An
event is a name, a user and the server's clock, and deliberately nothing
else: no properties column until a question needs one, because a JSON blob
here is where transcript text would eventually leak into a table with a
twelve-month lifetime.

`user_id` is a plain UUID like everywhere else, which is exactly why this
table must be named in the account-deletion purge — nothing cascades from a
user by design, and the completeness tests in `test_account_deletion.py`
refuse a user_id-carrying table without a deletion decision. The decision:
destroyed with the account, and swept at twelve months either way.

Revision ID: a2a2f34208ec
Revises: 22af72112ce1
Create Date: 2026-08-24 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'a2a2f34208ec'
down_revision: Union[str, Sequence[str], None] = '22af72112ce1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "app_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_app_events_user_at", "app_events", ["user_id", "at"])
    # Deny-all with no policies, like every table here: service-role access
    # through FastAPI is the real wall, and a policy-free RLS runs unchanged
    # on any Postgres (CLAUDE.md -> Database portability).
    op.execute("ALTER TABLE app_events ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_app_events_user_at", table_name="app_events")
    op.drop_table("app_events")
