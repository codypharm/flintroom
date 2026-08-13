"""refresh tokens

The long half of a session. The access token is unrevocable by design — nothing
is looked up to verify one — so this table is the only place a session can
actually be ended, which is why it is rows rather than another signed blob.

Only the SHA-256 of each token is stored. A leaked backup or an over-broad
SELECT therefore yields nothing usable. A plain hash rather than a slow KDF
because the input is 32 bytes of `secrets` output: no dictionary to run, nothing
for bcrypt to buy.

`family_id` is what makes theft actionable. Rotation leaves a thief and the
victim holding two tokens descended from one sign-in, so a replayed spent token
revokes the family and ends the session for both — which is the correct outcome,
because at that point we cannot tell which of the two is the real user.

Deny-all RLS, as every table (see 1f359ab487a7).

Backwards-compatible: a new table with no existing readers.

Revision ID: ca57fc4a0754
Revises: 98d4de1877d3
Create Date: 2026-08-13 07:04:08.240843

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ca57fc4a0754'
down_revision: Union[str, Sequence[str], None] = '98d4de1877d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('refresh_tokens',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('family_id', sa.UUID(), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['accounts.user_id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_refresh_tokens_family_id'), 'refresh_tokens', ['family_id'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)

    op.execute("ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON refresh_tokens "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS deny_all ON refresh_tokens")
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_family_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
