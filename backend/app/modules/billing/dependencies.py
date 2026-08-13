"""What a billing endpoint needs before it runs."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import CallerContext
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
