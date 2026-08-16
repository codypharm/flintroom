"""Reading a balance over HTTP.

What the app shows on the home screen. The presentation rule itself is settled
in `test_balance_display.py` — these are about the transport: who may read a
balance, and what the wire is allowed to carry.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from freezegun import freeze_time

from app.modules.billing.tiers import MONTHLY_ALLOWANCE_SECONDS


STARTER_MINUTES = MONTHLY_ALLOWANCE_SECONDS["starter"] // 60


async def test_a_caller_reads_their_own_remaining_minutes(
    client, funded_account, bearer
):
    """The tracer, and the whole response.

    Minutes and a yes/no, and deliberately nothing else. Product.md §4.6 forbids
    a depleting counter, and raw seconds on the wire is that counter with the
    arithmetic left to the client — every client would then invent its own
    rounding, and one of them would round up and promise a minute that is not
    there.
    """
    response = await client.get("/v1/balance", headers=bearer(funded_account.user_id))

    assert response.status_code == 200
    assert response.json() == {"remaining_minutes": 15, "has_time_remaining": True}


async def test_a_subscriber_whose_month_rolled_over_sees_the_new_allowance(
    client, account, bearer, db
):
    """The home screen must not disagree with the Start button.

    The monthly reset is lazy — there is no scheduler — so a subscriber whose
    period ended overnight has not been granted the new allowance until
    something asks for it. `SessionService.start` asks, which is what makes a
    plain balance read here a bug rather than a stale number: the screen would
    say zero minutes above a button that opens a room.
    """
    account.entitlement_tier = "starter"
    account.period_id = 1
    account.period_ends_at = datetime(2026, 5, 1, tzinfo=UTC)
    await db.commit()

    with freeze_time("2026-08-13"):
        response = await client.get("/v1/balance", headers=bearer(account.user_id))

    assert response.json() == {
        "remaining_minutes": STARTER_MINUTES,
        "has_time_remaining": True,
    }


async def test_reading_a_balance_needs_a_credential(client):
    """A balance is account data. Nobody reads it unauthenticated."""
    assert (await client.get("/v1/balance")).status_code == 401
