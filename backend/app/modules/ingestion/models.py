import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.ingestion.schemas import ClaimKind, MaterialState, Unit

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


#: Same VARCHAR-plus-CHECK shape as `material_state`, for the same reason: a
#: third claim kind should be a column addition, not an irreversible
#: `ALTER TYPE`.
claim_kind_column = Enum(
    ClaimKind,
    name="claim_kind",
    native_enum=False,
    length=16,
    values_callable=lambda enum: [member.value for member in enum],
)

claim_unit_column = Enum(
    Unit,
    name="claim_unit",
    native_enum=False,
    length=16,
    values_callable=lambda enum: [member.value for member in enum],
)


class MaterialClaim(Base):
    """One thing a deck asserts, and where in the deck it says it.

    This is not a cache of the document. The source is deleted once extraction
    succeeds (`docs/ingestion.md`), so these rows *are* the deck as far as
    everything downstream is concerned — anything extraction did not write here
    is permanently gone, which is why the extraction interface is allowed to be
    slow and expensive and is not allowed to be lossy.

    Both kinds live in one table because the Auditor reads them together: a
    panelist's ammunition for one slide is its figures *and* its assertions, and
    a `UNION` at every read is a poor trade for two sets of nullable columns the
    database enforces anyway.

    The split that *does* exist is against `session_claims` (task #29), and it
    is a retention split rather than a shape one. Deleting a session must not
    mean surgically removing rows from a store governed by another policy.
    """

    __tablename__ = "material_claims"
    __table_args__ = (
        CheckConstraint(
            f"kind IN ({_sql_values(ClaimKind)})", name="ck_material_claims_kind"
        ),
        # Written as one exhaustive disjunction rather than two implications,
        # because two implications permit an assertion that also carries a
        # metric — a row no reader is written to expect and every reader would
        # interpret differently. Each branch states what must be present *and*
        # what must be absent.
        CheckConstraint(
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
        CheckConstraint("page > 0", name="ck_material_claims_page"),
        # Every read is "the claims for this material", and the panel wants them
        # in reading order. Page is in the index so that ordering is free rather
        # than a sort over a deck's worth of rows.
        Index("ix_material_claims_material_id", "material_id", "page"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    #: Cascades, because `docs/ingestion.md` sets this table's retention to
    #: "until the user deletes the Material". A claim outliving its material is
    #: a fragment of a document the user believes they deleted.
    material_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("materials.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Denormalised from the material. Not for reads — those go through the
    #: material — but so that "everything belonging to this user" is answerable
    #: without a join, which is what a deletion request and the per-`user_id`
    #: sharding property both need.
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )

    #: Where in the deck. Reported by the model and, where the text layer could
    #: confirm it, corrected against it — see `quote_verified`.
    page: Mapped[int] = mapped_column(Integer, nullable=False)

    kind: Mapped[ClaimKind] = mapped_column(claim_kind_column, nullable=False)

    #: The source text, on both kinds. CLAUDE.md refuses interrogation logic
    #: that cannot cite its source, and this column is that citation. Stored,
    #: never logged: ingested material contents are forbidden in logs and,
    #: unlike a secret, are not detectable by key name.
    quote: Mapped[str] = mapped_column(Text, nullable=False)

    #: Whether the quote was found in the deck's own text layer. False for a
    #: figure read off a chart, which is unconfirmable rather than untrue — and
    #: worth telling apart before a panelist presses hardest on it.
    quote_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    metric: Mapped[str | None] = mapped_column(String(120), nullable=True)

    #: `Numeric`, not `Float`. A deck's figure is a decimal the user can read
    #: off a slide, and a panelist quoting 61.099999999999994 back at them is
    #: the specific failure `docs/auditor-grounding.md` says the grounding story
    #: cannot survive.
    value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)

    unit: Mapped[Unit | None] = mapped_column(claim_unit_column, nullable=True)
    period: Mapped[str | None] = mapped_column(String(60), nullable=True)

    subject: Mapped[str | None] = mapped_column(String(120), nullable=True)
    statement: Mapped[str | None] = mapped_column(String(600), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExtractionCost(Base):
    """What one extraction attempt cost, and what it produced.

    Separate from `session_costs` for the reason `docs/ingestion.md` gives: the
    metering boundary is locked to live interrogation, so **extraction is a real
    per-user cost with no revenue attached**, and the abuse case is precisely a
    deck that is extracted and never becomes a session. Attributing the cost to
    the session that used the material would leave exactly that case invisible.

    One row per *attempt*, not per material. A stalled `extracting` row is
    requeued by design, and a requeue is a second invoice — a table keyed on
    `material_id` would either refuse the second row or overwrite the first, and
    both of those under-report money already spent.
    """

    __tablename__ = "extraction_costs"
    __table_args__ = (
        Index("ix_extraction_costs_material_id", "material_id"),
        Index("ix_extraction_costs_user_id", "user_id", "recorded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    #: A plain UUID with no foreign key, deliberately — the one place this table
    #: departs from `session_costs`. Materials are user-deletable, and a
    #: cascading delete here would let "upload, extract, delete, repeat" erase
    #: its own trail: the abuse case §4.3 exists to make visible would be the
    #: one shape of usage that leaves no record. Same reasoning as
    #: `audit_events` — a row must survive deletion of what it describes.
    material_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    #: Denormalised for the same reason `session_costs` denormalises it: cost
    #: analysis groups by tier, and reading the tier live would re-price last
    #: quarter's extractions every time somebody upgraded. It is also the number
    #: that answers whether the free tier's page cap is set anywhere near right.
    tier: Mapped[str] = mapped_column(String(32), nullable=False)

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)

    pages: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    input_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    output_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )

    #: What the attempt produced. `claims_recorded` over `pages` is the
    #: cost-per-claim §4.3 needs; the other two are the quality signal, and this
    #: is the only per-attempt row there is to hang them on.
    claims_recorded: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    #: Claims the model returned in a shape nothing could use. A rising number
    #: is a deck grounding less than it appears to.
    claims_dropped: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    #: Claims whose page the text layer disagreed with, and moved. Not an error
    #: count — the correction is the mechanism working — but the rate is the
    #: only measure of how far the model's own page attribution can be trusted,
    #: and that is what should decide whether a page stays the locator at all.
    pages_corrected: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    #: Ours, from observed usage. Left null until a price table exists to
    #: compute it from — §4.3's acceptance criterion is that a computed figure
    #: and a provider invoice agree within 10%, and a number invented here from
    #: list rates would be the guess that criterion exists to replace.
    computed_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
