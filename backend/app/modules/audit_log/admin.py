"""Read-only views for operators.

Deliberately has no write methods. Anything an operator changes must go through
the owning service so it lands in the ledger or the audit trail with an ADMIN
actor attached — a support tool that writes directly is how an unexplained
balance appears.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import Actor
from app.modules.audit_log.models import AuditEvent
from app.modules.billing.models import LedgerEntry


class TimelineItem(BaseModel):
    """One row of an account's history, from either source."""

    kind: Literal["money", "event"]
    summary: str
    occurred_at: datetime
    actor: Actor
    actor_id: str | None = None
    request_id: str | None = None
    session_id: uuid.UUID | None = None

    #: Money rows only.
    delta_seconds: int | None = None
    balance_after_seconds: int | None = None
    bucket: str | None = None


class AdminService:
    """Operator-facing reads across the ledger and the audit trail."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def account_timeline(
        self, *, user_id: uuid.UUID, limit: int = 200
    ) -> list[TimelineItem]:
        """Money movements and audit events merged, most recent first.

        Merged in Python rather than by a UNION: the two tables have genuinely
        different shapes, and a SQL union would either lose columns or pad them
        with nulls that mean nothing.
        """
        entries = (
            await self._db.execute(
                select(LedgerEntry)
                .where(LedgerEntry.user_id == user_id)
                .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
                .limit(limit)
            )
        ).scalars()

        events = (
            await self._db.execute(
                select(AuditEvent)
                .where(AuditEvent.user_id == user_id)
                .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
                .limit(limit)
            )
        ).scalars()

        items = [
            TimelineItem(
                kind="money",
                summary=entry.reason,
                occurred_at=entry.created_at,
                actor=Actor(entry.actor),
                actor_id=entry.actor_id,
                request_id=entry.request_id,
                session_id=entry.session_id,
                delta_seconds=entry.delta_seconds,
                balance_after_seconds=entry.balance_after_seconds,
                bucket=entry.bucket,
            )
            for entry in entries
        ] + [
            TimelineItem(
                kind="event",
                summary=event.event_type,
                occurred_at=event.occurred_at,
                actor=Actor(event.actor),
                actor_id=event.actor_id,
                request_id=event.request_id,
                session_id=event.session_id,
            )
            for event in events
        ]

        items.sort(key=lambda item: item.occurred_at, reverse=True)
        return items[:limit]
