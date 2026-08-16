"""Material states and read models.

The lifecycle is specified in `docs/ingestion.md`.
"""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


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
