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


def _sql_values(enum: EnumType) -> str:
    """Render an enum's values as a SQL list.

    Generated rather than hand-typed so a new member cannot be added in Python
    while the database quietly keeps rejecting it.

    `EnumType` — the metaclass, which is what an enum class actually *is*.
    This read `type[Enum]`, and the `Enum` in scope here is **SQLAlchemy's**:
    the annotation claimed a column type where every caller passes a Python
    enum. Harmless at runtime and wrong to read, which is the class of thing
    only a checker finds.
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
        # The extraction sweep's claim query. Partial, because `ready` materials
        # accumulate for the life of the account and are never claimed —
        # indexing them would grow a hot index forever to answer a question
        # nobody asks about them.
        #
        # `retry_at` leads `created_at` because the claim filters on it before
        # it orders by anything: a requeued deck is not a candidate until its
        # wait is over, and scanning past every backed-off material to find that
        # out is what makes a rate-limit event slow down the decks that are fine.
        Index(
            "ix_materials_extractable",
            "state",
            "retry_at",
            "created_at",
            postgresql_where=text("state IN ('pending', 'extracting')"),
        ),
        # Decks whose bytes are still in the bucket after the material stopped
        # needing them. Partial, and it is the predicate doing all the work: a
        # successful delete sets `source_deleted_at` and drops the row straight
        # out of the index, so this stays near-empty in a healthy deployment and
        # its size is itself the signal that deletes are failing.
        Index(
            "ix_materials_source_undeleted",
            "created_at",
            postgresql_where=text(
                "source_deleted_at IS NULL AND state IN ('ready', 'failed')"
            ),
        ),
        # Materials the user has destroyed and the sweep has not yet removed.
        # Partial for the same reason as the index above, and even more one-sided:
        # a healthy deployment empties this within one pass, so anything durable
        # in it is an object the store is refusing to delete.
        Index(
            "ix_materials_deleted",
            "deleted_at",
            postgresql_where=text("deleted_at IS NOT NULL"),
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

    #: Where the downscaled first page lives, once one has been rendered.
    #:
    #: The only artefact that outlives the source document, and **not the
    #: low-sensitivity thing it sounds like**: a title slide routinely carries
    #: the company name, the round size and the word "Confidential". It inherits
    #: the claims' retention and deletion rules exactly and is never weaker.
    #:
    #: A separate key rather than a suffix on `storage_key`, so retention can be
    #: expressed as a bucket lifecycle rule over a prefix if it ever needs to be.
    thumbnail_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    #: When the uploaded document was removed from object storage.
    #:
    #: Both the record and the retry marker, which is why it is a timestamp
    #: rather than a boolean. The delete cannot join the transaction that settles
    #: the material — one is Postgres and the other is an HTTP call to a bucket —
    #: so the row is committed first and the object removed after. A delete that
    #: fails leaves this null, and a later pass tries again.
    #:
    #: Null on a material that is still readable, and on one whose extraction is
    #: waiting to be retried: a requeued deck still needs its bytes.
    source_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: When a sweep took this row, or null if nothing holds it. The crash-safety
    #: mark: a process that dies mid-extraction leaves `extracting` behind
    #: forever, and this is what lets a later pass tell a stalled claim from a
    #: live one. Written with the database's clock, because the requeue compares
    #: it against the database's clock.
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Do not claim this material before this moment, or null for "any time".
    #:
    #: The backoff lives in the queue rather than in a sleeping worker, which
    #: matters because the worker that would sleep is the one every other deck
    #: is waiting on. Written with the database's clock, because the claim query
    #: compares it against the database's clock.
    retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: How many times extraction was given back rather than finished.
    #:
    #: Counts the two endings that leave the deck worth trying again: a
    #: *retryable* result — a rate limit, a timeout, an overloaded provider —
    #: and a claim released because the process holding it died. A deck the API
    #: refuses outright fails on the first attempt, because retrying produces
    #: the same refusal, so it needs no budget.
    #:
    #: A crash is not the file's fault either, but it is counted for the same
    #: reason a rate limit is: without it, a deck that reliably kills the worker
    #: is claimed once per pass forever.
    #:
    #: The budget this counts against is deliberately generous. A rate limit is
    #: our capacity problem and not the user's file, so giving up early is
    #: exactly the data loss the classifier exists to prevent. The floor is
    #: there only so a pathological deck cannot be claimed forever.
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    #: When the user asked for this material to be destroyed.
    #:
    #: A mark rather than an immediate `DELETE`, and the row it keeps alive is
    #: measured in seconds. What it buys is a place for an extraction already in
    #: flight to land: a worker that has paid for a model call still has to write
    #: its `extraction_costs` row, and unrecorded spend on a deleted deck is
    #: precisely the abuse that table exists to make visible. The sweep removes
    #: the row for real once nothing holds it.
    #:
    #: It is not a grace period and nothing about it is undoable. The objects are
    #: deleted on the request, and from that moment the material is invisible to
    #: every read, every claim query and every room that tries to ground itself in
    #: it — so the user's promise is kept at the request and the row is our own
    #: bookkeeping.
    deleted_at: Mapped[datetime | None] = mapped_column(
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

    #: How many requests it took to read those pages. A full pro-tier deck does
    #: not fit in any context window in one piece, so it is read in chunks —
    #: and per-call overhead is repeated instruction tokens that `input_tokens`
    #: alone cannot be separated into. It is also the number that says whether
    #: the chunk size is set anywhere near right once real decks have run.
    calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

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
