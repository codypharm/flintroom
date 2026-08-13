"""voice tickets

A WebSocket handshake cannot carry an Authorization header from a browser, and
CLAUDE.md forbids mobile-only assumptions a web client would have to unpick. The
socket is admitted by a ticket in the query string instead — and because query
strings land in access logs, the ticket is single-use, expires in seconds, and
grants exactly one room.

`redeemed_at` is what makes single-use race-proof: the redeeming statement is an
UPDATE ... WHERE redeemed_at IS NULL, so two sockets presenting one ticket
contend on the row and exactly one comes back with a result.

Only the SHA-256 is stored, as with refresh_tokens. A leaked dump yields nothing
spendable.

Deny-all RLS, as every table (see 1f359ab487a7).

Backwards-compatible: a new table with no existing readers.

Revision ID: b2c4d6e8f0a1
Revises: 3a948f56c1ed
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b2c4d6e8f0a1'
down_revision: Union[str, Sequence[str], None] = '3a948f56c1ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'voice_tickets',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('ticket_hash', sa.String(length=64), nullable=False),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('redeemed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ticket_hash'),
    )
    op.create_index(
        op.f('ix_voice_tickets_session_id'), 'voice_tickets', ['session_id']
    )

    op.execute("ALTER TABLE voice_tickets ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON voice_tickets "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS deny_all ON voice_tickets")
    op.drop_index(op.f('ix_voice_tickets_session_id'), table_name='voice_tickets')
    op.drop_table('voice_tickets')
