"""material deletion

The column that lets a user destroy their own document.

`material_claims` has said since it was created that claims are kept *"until the
user deletes the Material"* — a retention rule describing an action no endpoint
offered. This is the column behind the endpoint that makes the sentence true.

A mark rather than an immediate `DELETE`, and the row survives it by seconds. The
window exists for one reason: an extraction already in flight has paid for a model
call and still has to write its `extraction_costs` row, and unrecorded spend on a
deleted deck is exactly the abuse that table has no foreign key in order to catch.
The sweep removes the row once nothing holds it.

It is not a grace period and nothing about it is recoverable. The objects are
deleted during the request, and from the moment this is set the material is
invisible to every read, every claim query, and every room that tries to ground
itself in it.

The index is partial and one-sided on purpose, like `ix_materials_source_undeleted`
above it: a healthy deployment drains it within one sweep pass, so anything that
lingers in it is an object the store is refusing to delete — the size of the index
is itself the alert.

Backwards-compatible with the previously deployed version: a nullable column and
a partial index, both invisible to a version that does not select them. Rolled
back with rows marked, those materials become visible again — the bytes are gone
regardless, so what returns is a row pointing at nothing, which is the same shape
as a material whose upload never landed.

Revision ID: b3c9d1e57a24
Revises: f20a42ee497f
Create Date: 2026-08-16 17:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3c9d1e57a24"
down_revision: str | Sequence[str] | None = "f20a42ee497f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "materials",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_materials_deleted",
        "materials",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_materials_deleted", table_name="materials")
    op.drop_column("materials", "deleted_at")
