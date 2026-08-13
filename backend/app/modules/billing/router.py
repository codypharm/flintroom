"""Billing endpoints.

Thin, per `CLAUDE.md`: parse the request, call a service, return a response.
"""

from fastapi import APIRouter

from app.modules.auth.dependencies import CurrentUser
from app.modules.billing.dependencies import LedgerServiceDep
from app.modules.billing.schemas import BalanceRead

router = APIRouter(tags=["billing"])


@router.get("/balance", response_model=BalanceRead)
async def read_balance(user_id: CurrentUser, ledger: LedgerServiceDep) -> BalanceRead:
    """How much interrogation time the caller has left.

    Through `ensure_current_period` rather than a plain read, because the
    monthly reset is lazy: a subscriber whose period rolled over overnight has
    not been granted the new month's allowance until something asks. A plain
    read would show them zero minutes on a screen whose Start button works.
    """
    return BalanceRead.model_validate(
        await ledger.ensure_current_period(user_id=user_id)
    )
