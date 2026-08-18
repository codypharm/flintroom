"""onboarding answers

The five questions of `docs/onboarding.md`, stored by lifetime rather than
together — the split decided with the architect on 2026-08-18.

Role and audience are durable: somebody is a product manager across every
roadmap review they ever rehearse, so they join the other per-account choices on
`user_preferences`, exactly as that table's docstring anticipated ("adding the
next preference [is] a column with a default rather than a backfill").

The situation and its date are an *event*, and events pass. "Board review in 6
days" is true this week and false next, so it is a row per occasion in a new
table — which is also what makes re-onboarding a second row rather than an
overwrite, and what the event countdown reads instead of the streak mechanic
`docs/onboarding.md` rejected.

Nothing is backfilled and nothing is dropped. Every existing account predates
the survey and has no true answer to write; `composition.compose` reads a null
role and an empty audience as "we know nothing about this meeting" and falls
through to the shipped default panel, which is the correct room for them.

Revision ID: a3c17b90e5d2
Revises: fd17209f748f
Create Date: 2026-08-18 16:41:07.882145

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a3c17b90e5d2'
down_revision: Union[str, Sequence[str], None] = 'fd17209f748f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "user_preferences",
        sa.Column("presenter_role", sa.String(length=32), nullable=True),
    )
    # Not null with an empty default, because "placed no chips" and "never saw
    # the question" produce the same room — a second empty state would be a
    # distinction nothing acts on.
    op.add_column(
        "user_preferences",
        sa.Column(
            "audience",
            postgresql.ARRAY(sa.String(length=32)),
            server_default="{}",
            nullable=False,
        ),
    )

    op.create_table(
        "situations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("happens_on", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_situations_user_created", "situations", ["user_id", "created_at"]
    )

    # Defense in depth, deny-all and free of `auth.uid()` so it runs unchanged
    # on any Postgres (CLAUDE.md -> Database portability).
    op.execute("ALTER TABLE situations ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON situations "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS deny_all ON situations")
    op.drop_index("ix_situations_user_created", table_name="situations")
    op.drop_table("situations")
    op.drop_column("user_preferences", "audience")
    op.drop_column("user_preferences", "presenter_role")
