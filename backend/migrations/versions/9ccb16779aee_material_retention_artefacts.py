"""material retention artefacts

What a deck leaves behind once it has been read, and the proof its bytes are gone.

`docs/ingestion.md` promises that *"what survives is the extracted claims and a
downscaled first-page thumbnail"* — a promise made to the App Store
questionnaire, not an optimisation. Until now the pipeline rendered that
thumbnail on every deck and discarded it, and never deleted the source at all,
so the one sentence the privacy answer rests on was false in both directions.

`thumbnail_key` is a separate key rather than a suffix on `storage_key`, so
retention can later be expressed as a bucket lifecycle rule over a prefix. It is
not the low-sensitivity artefact it sounds like: a title slide routinely carries
the company name, the round size and the word "Confidential", so it inherits the
claims' retention rules exactly and is never weaker.

`source_deleted_at` is both the record and the retry marker, which is why it is a
timestamp rather than a boolean. Removing an object cannot join the transaction
that settles the material — one is Postgres, the other an HTTP call to a bucket —
so the row commits first and the object goes after. A delete that fails leaves
this null and a later pass tries again, which is what stops a promise from being
broken by one bad afternoon in the storage layer.

`ix_materials_source_undeleted` is partial, and the predicate does all the work:
a successful delete drops the row straight out of the index, so this stays
near-empty in a healthy deployment and its size is itself the signal that
deletes are failing.

Backwards-compatible with the previously deployed version: both columns are
nullable with no default, and an older API neither writes nor reads them. Rolled
back, materials keep their source documents — which is the behaviour that
version already had.

Revision ID: 9ccb16779aee
Revises: 2da199d1c1bb
Create Date: 2026-08-16 13:58:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9ccb16779aee"
down_revision: str | Sequence[str] | None = "2da199d1c1bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNDELETED = sa.text("source_deleted_at IS NULL AND state IN ('ready', 'failed')")


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "materials", sa.Column("thumbnail_key", sa.String(length=512), nullable=True)
    )
    op.add_column(
        "materials",
        sa.Column("source_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_materials_source_undeleted",
        "materials",
        ["created_at"],
        unique=False,
        postgresql_where=UNDELETED,
    )


def downgrade() -> None:
    """Downgrade schema.

    Drops the record that a source was deleted, not the deletion. Objects
    already removed stay removed — there is nothing here that could bring them
    back — so a rollback loses the audit trail rather than reversing the act.
    """
    op.drop_index("ix_materials_source_undeleted", table_name="materials")
    op.drop_column("materials", "source_deleted_at")
    op.drop_column("materials", "thumbnail_key")
