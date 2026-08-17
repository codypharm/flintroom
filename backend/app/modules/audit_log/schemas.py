"""Audit event types and read models.

**Naming, deliberately.** This module is `audit_log`, never `auditor`. In
Flintroom's domain language the **Auditor** is the background agent that
cross-checks a live transcript against ingested material for contradictions.
This module is the compliance record of who did what. Colliding those two names
would make every future search for either one useless.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.actors import Actor


class AuditEventType(str, Enum):
    """Things worth being able to prove happened.

    Money movements are deliberately absent: they live in `ledger_entries`, and
    a second copy here would be a balance record that can silently disagree with
    the first.
    """

    # Session lifecycle — the half of an admin view the ledger cannot show.
    SESSION_STARTED = "session_started"
    SESSION_START_DENIED = "session_start_denied"
    SESSION_SETTLED = "session_settled"
    SESSION_REAPED = "session_reaped"

    # Entitlement and billing surface, excluding the balance change itself.
    ENTITLEMENT_CHANGED = "entitlement_changed"
    TOPUP_PURCHASED = "topup_purchased"
    WEBHOOK_REJECTED = "webhook_rejected"

    # Retention. The row outlives the thing it describes, which is the whole
    # point here: a promise to destroy a document is unfalsifiable without a
    # record that the user asked and we acted.
    MATERIAL_DELETED = "material_deleted"
    #: A room's audio reached the end of its tier's window and was removed.
    #: Unlike `MATERIAL_DELETED` nobody asked for this one — it is the published
    #: retention window being kept, and `docs/session-retention.md` chose an
    #: application sweep over a bucket lifecycle rule precisely so that there is
    #: a row to point at when somebody asks whether it was.
    RECORDING_EXPIRED = "recording_expired"

    # Security.
    PERMISSION_DENIED = "permission_denied"
    ADMIN_OVERRIDE = "admin_override"


class AuditEventRead(BaseModel):
    """One immutable audit row."""

    model_config = ConfigDict(from_attributes=True)

    event_type: AuditEventType
    actor: Actor
    actor_id: str | None = None
    request_id: str | None = None
    user_id: UUID | None = None
    session_id: UUID | None = None
    context: dict[str, Any]
    occurred_at: datetime | None = None
