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


class AuditService:
    """The only writer of `audit_events`."""

    def __init__(
        self,
        db: AsyncSession,
        actor: ActorContext | None = None,
        *,
        tag: str = "audit",
    ) -> None:
        self._db = db
        self._actor = actor or ActorContext.system()
        # The owning subsystem's tag, not this module's. A session's audit lines
        # and its ordinary lines are the same investigation, and splitting them
        # across two tags means filtering to `sessions` silently drops the start
        # and the settle — the two lines most worth having. The audit *table* is
        # unaffected; this only decides where the log line files itself.
        self._log = get_logger(__name__, tag=tag)

    def stage(
        self,
        event_type: AuditEventType,
        *,
        user_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        **context: Any,
    ) -> None:
        """Queue one audit row without committing. The caller commits.

        This is what lets an event land in the *same* transaction as the change
        it describes. Committing separately would mean a process that dies in
        between leaves either a state change nobody can explain or an audit row
        for something that never happened — and the first is precisely the row
        an operator will later be asked about.

        Context is redacted with the same rules as a log line. Applying them
        only to stdout would mean the first audit call carrying a webhook
        signature writes it to disk permanently — and these rows are
        append-only, so it could not be edited back out.
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
        self._log.info(
            event_type.value,
            user_id=str(user_id) if user_id else None,
            session_id=str(session_id) if session_id else None,
            **context,
        )

    async def record(
        self,
        event_type: AuditEventType,
        *,
        user_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        **context: Any,
    ) -> None:
        """Write one audit row on its own.

        For events with nothing else to commit alongside them — a denial, a
        rejected webhook. Where there *is* an accompanying write, use `stage`
        and let the owning service commit both together.
        """
        self.stage(event_type, user_id=user_id, session_id=session_id, **context)
        await self._db.commit()

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
