"""session costs

Product.md §4.3 requires this to ship with the first working voice loop, not
after it: every price in §4.4-4.5 rests on the unverified assumption that
interrogation costs ~$0.12/min because only one panelist speaks at a time. If
ElevenLabs bills per active agent session instead, every tier margin collapses,
and agent_session_count is the column that answers it.

Separate from ledger_entries on purpose. The ledger is what the user owes and is
the audited money record; this is what the provider charges us — a different
number that arrives later and may disagree. Merged, a reconciliation discrepancy
would be indistinguishable from a billing bug.

Keyed by session_id rather than a surrogate: one row per session is the
invariant, and making it the primary key is what enforces it.

Deny-all RLS, as every table (see 1f359ab487a7).

Backwards-compatible: a new table with no existing readers.

Revision ID: d4e6f8a0b2c3
Revises: b2c4d6e8f0a1
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd4e6f8a0b2c3'
down_revision: Union[str, Sequence[str], None] = 'b2c4d6e8f0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'session_costs',
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tier', sa.String(length=32), nullable=False),
        sa.Column(
            'interrogation_seconds', sa.Integer(), server_default='0', nullable=False
        ),
        sa.Column(
            'agent_session_count', sa.Integer(), server_default='0', nullable=False
        ),
        sa.Column(
            'tts_characters_synthesized',
            sa.BigInteger(),
            server_default='0',
            nullable=False,
        ),
        sa.Column(
            'stt_seconds_processed', sa.Integer(), server_default='0', nullable=False
        ),
        sa.Column(
            'llm_input_tokens', sa.BigInteger(), server_default='0', nullable=False
        ),
        sa.Column(
            'llm_output_tokens', sa.BigInteger(), server_default='0', nullable=False
        ),
        sa.Column(
            'auditor_invocations', sa.Integer(), server_default='0', nullable=False
        ),
        sa.Column('debrief_seconds', sa.Integer(), server_default='0', nullable=False),
        sa.Column('sparring_seconds', sa.Integer(), server_default='0', nullable=False),
        sa.Column('computed_cost_usd', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column(
            'provider_reported_cost', sa.Numeric(precision=12, scale=6), nullable=True
        ),
        sa.Column(
            'recorded_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('session_id'),
    )

    op.execute("ALTER TABLE session_costs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON session_costs "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS deny_all ON session_costs")
    op.drop_table('session_costs')
