"""materials

The row a deck gets before it becomes claims. `docs/ingestion.md` specifies the
lifecycle; the constraints here are the parts of it the database can enforce
without trusting a service to have remembered.

Two invariants are worth more than the column list:

`ck_materials_claimed_at` ties the claim mark to `extracting`. A claimed row in
any other state is invisible to the requeue sweep while still looking busy, and
an `extracting` row without a claim is one no sweep can ever time out. Either
way the material never finishes and never fails, and nobody is told.

`uq_materials_storage_key` is unique across accounts rather than within one. The
key contains the owner, so a collision would be one account's deck served to
another — which is worth a constraint rather than a convention.

RLS deny-all, no `auth.uid()`, matching migration `1f359ab487a7`. The policy is
redundant against Postgres semantics — RLS enabled with no policy already denies
everyone — and written anyway so the intent is visible in `pg_policies` rather
than reading as an oversight.

Backwards-compatible with the previously deployed version: new tables only, so
an older API talking to this schema behaves identically.

Revision ID: 0d78b914fbba
Revises: d4e6f8a0b2c3
Create Date: 2026-08-16 08:14:22.113847

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0d78b914fbba"
down_revision: str | Sequence[str] | None = "d4e6f8a0b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "materials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "awaiting_upload",
                "pending",
                "extracting",
                "ready",
                "failed",
                name="material_state",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('awaiting_upload', 'pending', 'extracting', 'ready', 'failed')",
            name="ck_materials_state",
        ),
        sa.CheckConstraint(
            "(state = 'extracting') = (claimed_at IS NOT NULL)",
            name="ck_materials_claimed_at",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_materials_user_id", "materials", ["user_id"])
    op.create_index(
        "uq_materials_storage_key", "materials", ["storage_key"], unique=True
    )
    op.create_index(
        "ix_materials_extractable",
        "materials",
        ["state", "created_at"],
        postgresql_where=sa.text("state IN ('pending', 'extracting')"),
    )

    op.execute("ALTER TABLE materials ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY deny_all ON materials "
        "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS deny_all ON materials")
    op.drop_index("ix_materials_extractable", table_name="materials")
    op.drop_index("uq_materials_storage_key", table_name="materials")
    op.drop_index("ix_materials_user_id", table_name="materials")
    op.drop_table("materials")
