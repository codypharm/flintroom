"""session materials

Which decks a room was grounded in — the join that makes ingestion reachable.

Until now `POST /v1/sessions` took no request body at all: a session was *"open a
room for the caller"* and carried no configuration, so material had nowhere to
attach even once it existed. Everything in ingestion ran in its own corner.

Many-to-many, and genuinely so. `docs/ingestion.md` owns material by *account*
rather than by session, because the product's premise is repeat rehearsal before
one event — a deck uploaded once and used across five sessions is the normal
case. In the other direction one session can carry a deck plus a photograph of
the whiteboard beside it.

A composite primary key rather than a surrogate id: the pair *is* the fact, and
it makes attaching the same deck to one room twice impossible rather than merely
unlikely.

Both foreign keys cascade. On the material side that means deleting a deck
erases the record that a past session used it — deliberate, because
`material_claims` cascades with it too, so the grounding is gone either way and
a link pointing at contents that no longer exist is a citation nobody can
follow.

Deny-all RLS without `auth.uid()`, like every other table (migration
`1f359ab487a7`). Defense in depth: the real wall is that all access goes through
FastAPI, and a policy free of Supabase auth helpers runs unchanged on any
Postgres.

Backwards-compatible with the previously deployed version: a new table nothing
older reads or writes. Rolled back, sessions lose their attached material and
become the unconfigured rooms that version already opened.

Revision ID: f20a42ee497f
Revises: 9ccb16779aee
Create Date: 2026-08-16 14:32:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f20a42ee497f"
down_revision: str | Sequence[str] | None = "9ccb16779aee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "session_materials",
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("material_id", sa.UUID(), nullable=False),
        sa.Column(
            "attached_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "session_id", "material_id", name="pk_session_materials"
        ),
    )
    # The reverse lookup: "which rooms used this deck". Not needed by anything
    # today, and it is what a deletion request asks — plus Postgres does not
    # index the second column of a composite key, so a cascading delete of a
    # material would otherwise scan this table.
    op.create_index(
        "ix_session_materials_material_id", "session_materials", ["material_id"]
    )

    op.execute("ALTER TABLE session_materials ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON session_materials "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS deny_all ON session_materials")
    op.drop_index("ix_session_materials_material_id", table_name="session_materials")
    op.drop_table("session_materials")
