"""material claims and extraction costs

What survives a deck, and what reading it cost.

`material_claims` is not a cache. The source document is deleted once extraction
succeeds (`docs/ingestion.md`), so these rows are the deck as far as everything
downstream is concerned — which is why `ck_material_claims_kind_fields` is
written as one exhaustive disjunction rather than two implications. Two
implications would permit an assertion carrying a metric: a row no reader
expects and every reader would interpret differently.

`extraction_costs` deliberately has **no foreign key** to `materials`, and that
is the one place it departs from `session_costs`. Materials are user-deletable,
and a cascading delete would let "upload, extract, delete, repeat" erase its own
trail — the abuse case §4.3 exists to make visible would be the one shape of
usage leaving no record. Same reasoning as `audit_events`: a row must survive
deletion of whatever it describes.

RLS deny-all, no `auth.uid()`, matching migration `1f359ab487a7`.

Backwards-compatible with the previously deployed version: new tables only, so
an older API talking to this schema behaves identically.

Revision ID: f5d995026695
Revises: 9fbca1372236
Create Date: 2026-08-16 10:41:07.442119

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f5d995026695"
down_revision: str | Sequence[str] | None = "9fbca1372236"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNITS = ("percent", "usd", "eur", "gbp", "multiple", "count", "unknown")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "material_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("material_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "quantitative",
                "assertion",
                name="claim_kind",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column(
            "quote_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("metric", sa.String(length=120), nullable=True),
        sa.Column("value", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column(
            "unit",
            sa.Enum(*UNITS, name="claim_unit", native_enum=False, length=16),
            nullable=True,
        ),
        sa.Column("period", sa.String(length=60), nullable=True),
        sa.Column("subject", sa.String(length=120), nullable=True),
        sa.Column("statement", sa.String(length=600), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('quantitative', 'assertion')", name="ck_material_claims_kind"
        ),
        sa.CheckConstraint(
            "("
            "  kind = 'quantitative'"
            "  AND metric IS NOT NULL AND value IS NOT NULL AND unit IS NOT NULL"
            "  AND subject IS NULL AND statement IS NULL"
            ") OR ("
            "  kind = 'assertion'"
            "  AND subject IS NOT NULL AND statement IS NOT NULL"
            "  AND metric IS NULL AND value IS NULL AND unit IS NULL"
            "  AND period IS NULL"
            ")",
            name="ck_material_claims_kind_fields",
        ),
        sa.CheckConstraint("page > 0", name="ck_material_claims_page"),
        sa.ForeignKeyConstraint(
            ["material_id"], ["materials.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_material_claims_material_id", "material_claims", ["material_id", "page"]
    )
    op.create_index("ix_material_claims_user_id", "material_claims", ["user_id"])

    op.create_table(
        "extraction_costs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("material_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tier", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("pages", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "claims_recorded", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("claims_dropped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pages_corrected", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "computed_cost_usd", sa.Numeric(precision=12, scale=6), nullable=True
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extraction_costs_material_id", "extraction_costs", ["material_id"]
    )
    op.create_index(
        "ix_extraction_costs_user_id", "extraction_costs", ["user_id", "recorded_at"]
    )

    for table in ("material_claims", "extraction_costs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY deny_all ON {table} "
            "AS PERMISSIVE FOR ALL TO PUBLIC USING (false) WITH CHECK (false)"
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in ("material_claims", "extraction_costs"):
        op.execute(f"DROP POLICY IF EXISTS deny_all ON {table}")

    op.drop_index("ix_extraction_costs_user_id", table_name="extraction_costs")
    op.drop_index("ix_extraction_costs_material_id", table_name="extraction_costs")
    op.drop_table("extraction_costs")

    op.drop_index("ix_material_claims_user_id", table_name="material_claims")
    op.drop_index("ix_material_claims_material_id", table_name="material_claims")
    op.drop_table("material_claims")
