"""Writing and reading the audit trail.

Distinct from application logging: logs are for debugging and may be sampled,
dropped or rotated away. These rows may not — they are what an operator relies
on during a billing dispute or a security review.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.logging import get_logger, redact
from app.modules.audit_log.models import AuditEvent
from app.modules.audit_log.schemas import AuditEventRead, AuditEventType

log = get_logger(__name__, tag="audit")


class AuditService:
    """The only writer of `audit_events`."""

    def __init__(self, db: AsyncSession, actor: ActorContext | None = None) -> None:
        self._db = db
        self._actor = actor or ActorContext.system()

    async def record(
        self,
        event_type: AuditEventType,
        *,
        user_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        **context: Any,
    ) -> None:
        """Write one audit row.

        Context is redacted with the same rules as a log line. Applying them only
        to stdout would mean the first audit call carrying a webhook signature
        writes it to disk permanently — and these rows are append-only, so it
        could not be edited back out.
        """
        self._db.add(
            AuditEvent(
                event_type=event_type.value,
                actor=self._actor.actor.value,
                actor_id=self._actor.actor_id,
                request_id=self._actor.request_id,
                user_id=user_id,
                session_id=session_id,
                context=redact(context),
            )
        )
        await self._db.commit()

        log.info(
            event_type.value,
            user_id=str(user_id) if user_id else None,
            session_id=str(session_id) if session_id else None,
            **context,
        )

    async def events_for_user(
        self, *, user_id: uuid.UUID | None, limit: int = 100
    ) -> list[AuditEventRead]:
        """Most recent first — an operator reads backwards from the incident."""
        result = await self._db.execute(
            select(AuditEvent)
            .where(AuditEvent.user_id == user_id)
            .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
            .limit(limit)
        )
        return [AuditEventRead.model_validate(row) for row in result.scalars()]
