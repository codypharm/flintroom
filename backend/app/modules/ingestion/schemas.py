"""Material states and read models.

The lifecycle is specified in `docs/ingestion.md`.
"""

from enum import Enum


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
