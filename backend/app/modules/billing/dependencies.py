"""What a billing endpoint needs before it runs."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import Actor, ActorContext
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.modules.auth.dependencies import CallerContext
from app.modules.billing.billing import BillingService
from app.modules.billing.service import LedgerService


async def get_ledger_service(
    caller: CallerContext,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LedgerService:
    """The ledger, attributed to the account holder.

    Every entry written through a request carries `USER` rather than the
    `SYSTEM` default — which is the difference between "this account was
    granted minutes" and being able to say who caused it.
    """
    return LedgerService(db, actor=caller)


LedgerServiceDep = Annotated[LedgerService, Depends(get_ledger_service)]


def get_webhook_secret(
    settings: Annotated[Settings, Depends(get_settings)],
) -> str | None:
    """What callbacks are verified against, or nothing if none is configured.

    Returns the absence rather than raising on it, so that every refusal —
    unconfigured, unsigned, forged, stale — is decided and recorded in one place.
    A dependency that raised would produce the single refusal with no audit row,
    which is the one an operator most needs to see: it means purchases are being
    dropped on the floor.
    """
    return settings.revenuecat_webhook_secret or None


WebhookSecret = Annotated[str | None, Depends(get_webhook_secret)]


async def get_billing_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BillingService:
    """Billing as the store's callbacks reach it.

    `WEBHOOK` rather than `USER`, and not a detail: there is no caller here to
    attribute anything to. A purchase credited under the account holder would
    read as something they did in the app, and the first question asked of an
    unexplained balance is who moved it.
    """
    return BillingService(db, actor=ActorContext(actor=Actor.WEBHOOK))


BillingServiceDep = Annotated[BillingService, Depends(get_billing_service)]
