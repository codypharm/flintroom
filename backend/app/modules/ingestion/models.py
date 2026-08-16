import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.ingestion.schemas import MaterialState

#: A VARCHAR rather than a native Postgres enum, for the reason `sessions`
#: records: `ALTER TYPE ... ADD VALUE` cannot be reversed, which would make
#: adding a sixth state a migration hazard. The CHECK is declared by hand below
#: rather than through `create_constraint`, so it lives in the model metadata
#: and Alembic autogenerate does not emit a `drop_constraint` for it later.
material_state_column = Enum(
    MaterialState,
    name="material_state",
    native_enum=False,
    length=16,
    values_callable=lambda enum: [member.value for member in enum],
)


def _sql_values(enum: type[Enum]) -> str:
    """Render an enum's values as a SQL list.

    Generated rather than hand-typed so a new member cannot be added in Python
    while the database quietly keeps rejecting it.
    """
    return ", ".join(f"'{member.value}'" for member in enum)


class Material(Base):
    """One attached document, from presign through to extracted claims.

    Owned by an account rather than by a session (`docs/ingestion.md`): the
    product's premise is repeat rehearsal before one event, so a deck used
    across five sessions is the normal case. It also puts retention on the
    thing a privacy policy is actually written about.
    """

    __tablename__ = "materials"
    __table_args__ = (
        CheckConstraint(
            f"state IN ({_sql_values(MaterialState)})", name="ck_materials_state"
        ),
        # Claimed and extracting are the same fact. A claimed row in any other
        # state is invisible to the requeue sweep while still looking busy, and
        # an `extracting` row without a claim is one no sweep can ever time out
        # — both are a material that never finishes and never fails.
        CheckConstraint(
            "(state = 'extracting') = (claimed_at IS NOT NULL)",
            name="ck_materials_claimed_at",
        ),
        # One object per material, so a retried upload cannot orphan bytes that
        # nothing points at. Unique across accounts rather than within one: the
        # key already contains the owner, and a collision between users would be
        # one account's deck served to another.
        Index("uq_materials_storage_key", "storage_key", unique=True),
        # The extraction sweep's claim query. Partial, because `ready` materials
        # accumulate for the life of the account and are never claimed —
        # indexing them would grow a hot index forever to answer a question
        # nobody asks about them.
        Index(
            "ix_materials_extractable",
            "state",
            "created_at",
            postgresql_where=text("state IN ('pending', 'extracting')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    #: Plain UUID, never a foreign key to `auth.users` — see CLAUDE.md
    #: → Database portability.
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )

    state: Mapped[MaterialState] = mapped_column(material_state_column, nullable=False)

    #: What the user called it, for display only. Never used to build a path:
    #: a filename arrives from a phone and can contain anything, and the one
    #: place it could do damage is the one place it is not allowed to reach.
    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    #: Declared by the client and validated before the presign is issued, so a
    #: wrong type costs no upload. Re-checked against the extracted bytes later:
    #: this value is a claim by the caller until something has read the file.
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)

    #: Declared by the client, and binding rather than advisory: it is signed
    #: into the presigned PUT, so the object either has exactly this many bytes
    #: or it was never accepted. That is what makes this column safe to compare
    #: a tier cap against without re-reading the object.
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    #: Where the object lives, derived rather than chosen by the caller. A
    #: caller-supplied key is a caller who can write over somebody else's.
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    #: When a sweep took this row, or null if nothing holds it. The crash-safety
    #: mark: a process that dies mid-extraction leaves `extracting` behind
    #: forever, and this is what lets a later pass tell a stalled claim from a
    #: live one. Written with the database's clock, because the requeue compares
    #: it against the database's clock.
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
