"""Billing endpoints.

Thin, per `CLAUDE.md`: parse the request, call a service, return a response.
"""

from fastapi import APIRouter, Request

from app.modules.auth.dependencies import CurrentUser
from app.modules.billing.dependencies import (
    BillingServiceDep,
    LedgerServiceDep,
    WebhookSecret,
)
from app.modules.billing.revenuecat import SIGNATURE_HEADER
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


@router.post("/webhooks/revenuecat", status_code=200, include_in_schema=False)
async def receive_revenuecat(
    request: Request, billing: BillingServiceDep, secret: WebhookSecret
) -> dict[str, str]:
    """What the store tells us about a purchase.

    The one endpoint here that takes a `Request` rather than a parsed body, and
    it has to: the signature covers the **raw bytes**, so a handler that accepted
    a Pydantic model would be verifying against a re-serialization — under which
    any two bodies that parse the same become interchangeable. There is no
    `response_model` for the same reason there is no request model.

    No authentication dependency, because the caller is not a user and holds no
    token. The shared secret is the whole of the auth, which is why the service
    checks it before reading a single field.

    `include_in_schema=False`: `contracts/openapi.yaml` is the contract our
    client generates from, and RevenueCat is not our client. Publishing this
    would put a route no app may call into the app's own types.

    200 with a body nobody reads. RevenueCat retries any other status five times
    over roughly two and a half hours, so the only thing worse than answering
    wrongly here is answering slowly.
    """
    await billing.receive_revenuecat(
        body=await request.body(),
        signature=request.headers.get(SIGNATURE_HEADER),
        secret=secret,
    )
    return {"status": "ok"}
