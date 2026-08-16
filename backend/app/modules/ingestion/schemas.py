"""Material states and read models.

The lifecycle is specified in `docs/ingestion.md`.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MaterialState(str, Enum):
    """The five states an attached material can be in.

    ```
    awaiting_upload ──► pending ──► extracting ──► ready
           │                                 └──► failed
           └──► (reaped — a presign nobody used)
    ```

    `awaiting_upload` exists because the row precedes the object: the presign is
    signed against a key, and ownership is checked on a row. Without it,
    `pending` would mean both "no bytes yet" and "bytes here, waiting its turn",
    and the extraction sweep claims `pending` — so it would pick up materials
    nobody ever uploaded and pay a model to read nothing.

    `extracting` exists for the same reason `finalizing` does on a session:
    without it nothing separates "still working" from "the process died", and
    the requeue cannot be safe. Unlike settlement, a duplicate run here is not a
    refused write — it is a second invoice.

    `failed` is terminal and deliberately not retried in place. A material that
    could not be read is re-uploaded, because the source document is deleted on
    success and there is nothing to reprocess from.
    """

    AWAITING_UPLOAD = "awaiting_upload"
    PENDING = "pending"
    EXTRACTING = "extracting"
    READY = "ready"
    FAILED = "failed"


#: The four inputs `docs/ingestion.md` accepts, minus pasted text — which is not
#: an upload and never reaches object storage.
#:
#: An allowlist rather than a blocklist, and checked before the presign so a
#: wrong type costs no upload. The type is also signed into the URL, so this is
#: not merely a note on the row: the store refuses a body sent under any other
#: type. It stays a claim by the caller until `parsing.py` reads the bytes —
#: what is guaranteed here is that the object matches what was declared, not
#: that the declaration was true.
#:
#: HEIC is in the list because it is what an iPhone camera produces by default,
#: and photographing a whiteboard is the mobile-native case in §3.2. Omitting it
#: would refuse the most likely photo on the most likely device.
ACCEPTED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "image/jpeg",
        "image/png",
        "image/heic",
        "image/heif",
    }
)


class Unit(str, Enum):
    """The closed set a figure's unit is reduced to before anything compares it.

    Closed on purpose. `docs/auditor-grounding.md` names comparability as the
    source of most false positives, and a free-text unit makes `61 "%"` and
    `61 "percent"` two different figures — so a margin restated in different
    words reads as a contradiction that is not there.

    Currencies stay distinct rather than collapsing into one "currency" member.
    €4M and $4M are genuinely different claims, and flattening them would invent
    an agreement between them.
    """

    PERCENT = "percent"
    USD = "usd"
    EUR = "eur"
    GBP = "gbp"
    MULTIPLE = "multiple"
    COUNT = "count"
    UNKNOWN = "unknown"


#: What a model might write, and what it means. Lowercased and stripped before
#: lookup, so only genuinely distinct spellings need an entry.
_UNIT_SPELLINGS: dict[str, Unit] = {
    "%": Unit.PERCENT,
    "pct": Unit.PERCENT,
    "percent": Unit.PERCENT,
    "percentage": Unit.PERCENT,
    "$": Unit.USD,
    "usd": Unit.USD,
    "dollar": Unit.USD,
    "dollars": Unit.USD,
    "€": Unit.EUR,
    "eur": Unit.EUR,
    "euro": Unit.EUR,
    "euros": Unit.EUR,
    "£": Unit.GBP,
    "gbp": Unit.GBP,
    "pound": Unit.GBP,
    "pounds": Unit.GBP,
    "x": Unit.MULTIPLE,
    "×": Unit.MULTIPLE,
    "times": Unit.MULTIPLE,
    "multiple": Unit.MULTIPLE,
    "count": Unit.COUNT,
    "units": Unit.COUNT,
    "people": Unit.COUNT,
    "users": Unit.COUNT,
    "customers": Unit.COUNT,
}


def normalize_unit(written: str) -> Unit:
    """Whatever the model wrote, as a member of the closed set.

    Unrecognised spellings become `UNKNOWN` rather than being guessed at. Deny by
    default, applied to arithmetic: guessing produces exactly the comparison that
    should never have happened, and silently. `UNKNOWN` costs a missed catch
    instead of a false accusation, which is the direction
    `docs/auditor-grounding.md` says to err in — *"a false accusation is worse
    than a missed catch"*.
    """
    cleaned = written.strip().lower()
    if cleaned in _UNIT_SPELLINGS:
        return _UNIT_SPELLINGS[cleaned]

    # "8x" and "3.5×" are how a multiple is usually written, value included.
    if cleaned.rstrip("x×") != cleaned and _is_number(cleaned.rstrip("x×")):
        return Unit.MULTIPLE

    return Unit.UNKNOWN


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


class ClaimKind(str, Enum):
    """The two things a deck asserts, and only one of them is a number.

    Carried explicitly rather than inferred from which fields happen to be set.
    A discriminator reconstructed by looking for a null is one that starts
    disagreeing with itself the moment a field becomes optional.
    """

    QUANTITATIVE = "quantitative"
    ASSERTION = "assertion"


class ClaimCore(BaseModel):
    """What both kinds carry.

    `quote` is the source text every claim traces back to. CLAUDE.md: *"do not
    ship interrogation logic that can't cite its source"* — so it is required on
    both kinds, and it is stored and **never logged**. Ingested material
    contents are forbidden in logs and, unlike a secret, are not detectable by
    key name, so the text must not be passed to a log call at all.
    """

    model_config = ConfigDict(extra="forbid")

    quote: str = Field(min_length=1, max_length=2000)


class QuantitativeClaim(ClaimCore):
    """One figure, captured with enough context to compare it to another.

    The shape is shared with the claims the Auditor pulls out of live speech
    (`docs/auditor-grounding.md`), because comparing a slide's figure against a
    spoken one is the Auditor's entire function and they must be comparable. The
    *locator* differs — a slide number here, an offset into the session there —
    and lives on the row rather than in this type.

    This is the only kind that supports exact contradiction, which is the bar
    `docs/auditor-grounding.md` sets for interrupting a live room: a
    contradiction stateable precisely, both figures and both moments.
    """

    kind: Literal[ClaimKind.QUANTITATIVE] = ClaimKind.QUANTITATIVE

    #: What is being measured — "gross margin", "ARR", "headcount".
    metric: str = Field(min_length=1, max_length=120)

    #: A number, never prose. "1.2M" is the shape a model reaches for and it is
    #: refused here rather than parsed: a parser is code guessing at magnitude,
    #: and a magnitude guessed wrong is a claim off by a factor of a million,
    #: asserted confidently in a panelist's voice.
    value: float

    unit: Unit

    #: What the figure covers — "Q3 2026", "FY2025". Optional, because headcount
    #: today has no period and refusing it would drop a real claim.
    period: str | None = Field(default=None, max_length=60)

    @field_validator("unit", mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        """Normalise on the way in, so the type carries the guarantee.

        A free-standing normaliser is one somebody constructs a `Claim` without
        calling, and that failure is invisible until two figures which should
        have matched do not.
        """
        return normalize_unit(value) if isinstance(value, str) else value

    def comparable_to(self, other: QuantitativeClaim) -> bool:
        """Whether these two figures may be checked against each other at all.

        Asked as a question rather than inferred from equality of units, because
        `UNKNOWN` is not a unit two figures can share — normalising everything
        unrecognised to one token would otherwise make "furlongs" and "widgets"
        agree.

        Period must match for the reason the grounding doc gives by name: last
        quarter's revenue against last year's is not a contradiction, and without
        the period on both it looks exactly like one.
        """
        return (
            self.unit is not Unit.UNKNOWN
            and self.unit is other.unit
            and self.period == other.period
        )


class AssertionClaim(ClaimCore):
    """A statement the deck makes that is not a number.

    `Product.md` asks extraction for *"claims, figures, and chart data"* and the
    Auditor for *"contradictions, unsupported claims, and figures that moved"* —
    claims and figures distinguished throughout. Most of what is genuinely
    attackable in a deck lives here: exclusivity, a granted patent, a
    competitive absolute, a promise about next quarter. Without it the Technical
    Skeptic has no ammunition and the panel is one archetype wearing four hats.

    Deliberately has no `comparable_to`. Fuzzy disagreement must not reach a live
    interruption — `docs/auditor-grounding.md` collects qualitative findings for
    the debrief instead, because *"a false accusation is worse than a missed
    catch"* and a panel that pounces on a paraphrase is not intimidating, it is
    stupid.
    """

    kind: Literal[ClaimKind.ASSERTION] = ClaimKind.ASSERTION

    #: The domain the statement belongs to — "distribution", "intellectual
    #: property", "competition". §3.3 assigns the interrupter by domain, and
    #: without this every assertion is unroutable and targeted interruption
    #: quietly covers only numbers.
    subject: str = Field(min_length=1, max_length=120)

    statement: str = Field(min_length=1, max_length=600)


#: Either kind, discriminated by `kind` rather than by trial parsing. Pydantic
#: picks the member from the tag, so a malformed entry fails against one schema
#: with a useful error instead of failing against both with a confusing union.
Claim = Annotated[
    QuantitativeClaim | AssertionClaim, Field(discriminator="kind")
]


class MaterialDeclaration(BaseModel):
    """What the client says it is about to upload.

    Every field is a claim, and each is made binding by something other than
    trust: the size and the type are signed into the URL, so the store refuses a
    body that disagrees, and the filename is display-only and never reaches a
    path.

    `byte_size` is bounded on both ends here rather than only against the tier
    cap. The lower bound is what stops a negative length reaching the signer,
    where it becomes a vendor-specific error instead of a refusal; the upper is
    a sanity bound well above the largest tier, so an absurd number is a 422
    from the schema rather than arithmetic anybody has to reason about.
    """

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    byte_size: int = Field(gt=0, le=1024 * 1024 * 1024)


class MaterialRead(BaseModel):
    """One material, as the client sees it.

    `storage_key` is deliberately absent. It is an internal locator, and the
    only legitimate way to reach an object is a presigned URL this service
    issues after checking ownership — a key in a response is an invitation to
    build a client that constructs its own.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    state: MaterialState
    filename: str
    content_type: str
    byte_size: int
    created_at: datetime


class MaterialUpload(MaterialRead):
    """A registered material, and the one URL that may receive its bytes.

    Returned only from the register call, never from a read. The URL is a bearer
    credential for a single object at a single size — short-lived by
    construction, and not the kind of thing to hand back on every GET.
    """

    upload_url: str


class TierUpload(BaseModel):
    """What a tier accepts, for a client drawing an upgrade prompt."""

    tier: str
    max_upload_bytes: int
    max_pages_per_material: int


class MaterialLimits(TierUpload):
    """The caller's own caps, and the rung above if there is one.

    Published so the app can refuse an oversized file locally — instantly, with
    no round trip and no partial upload — while the server refusal stays the
    real wall. The alternative was the client holding its own copy of the tier
    table, where a pricing change ships as an app release and the two can
    disagree without anyone noticing.
    """

    accepted_content_types: list[str]
    upgrade: TierUpload | None = Field(default=None)
