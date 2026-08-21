"""The runaway-cost circuit breaker, which `CLAUDE.md` named and nothing built.

Metering Rules list it in one line — *"per-account daily spend ceiling as a
runaway-cost circuit breaker"* — and `docs/voice-cost.md` leans on it in as many
words: the abuse loop is start, end, start, bounded by the one-active-session
rule to "on the order of a dollar an hour per account, **against a daily spend
ceiling that exists to catch exactly that**". It did not exist.

It is a *cost* control and never a revenue one. A room under one tick is free to
the user and that must not change — charging for a room somebody abandoned in
ten seconds is the "silently over-charged" failure the metering rules exist to
prevent. What this bounds is what three providers can be made to charge us for a
room the meter will never bill.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import DailyCeilingReached
from app.modules.audit_log.schemas import AuditEventType
from app.modules.audit_log.models import AuditEvent
from app.modules.billing.models import Account
from app.modules.billing.tiers import DAILY_SPEND_CEILING_USD
from app.modules.sessions.models import Session
from app.modules.sessions.schemas import EndReason, SessionState
from app.modules.sessions.service import SessionService
from app.modules.voice.costs import SessionCost

pytestmark = pytest.mark.asyncio


async def _spent(db, account, usd: str, *, ago: timedelta = timedelta(hours=1)) -> None:
    """A settled room that cost us `usd`, recorded `ago`.

    Written directly rather than by running a room: this is about the ceiling's
    arithmetic, and driving three providers to produce a specific dollar figure
    would test the rate table twice and the ceiling once.
    """
    from app.core.database import db_now

    # A settled room, because `session_costs.session_id` is a foreign key. Its
    # state is what a spent room actually looks like, and inserting it directly
    # keeps this out of the one-live-session rule.
    room = Session(
        user_id=account.user_id,
        state=SessionState.SETTLED,
        # `ck_sessions_settled_at` insists, and it is right to: a settled room
        # with no settling time is the shape every retention and reconciliation
        # query would silently skip.
        settled_at=await db_now(db),
        end_reason=EndReason.USER_ENDED,
    )
    db.add(room)
    await db.flush()

    db.add(
        SessionCost(
            session_id=room.id,
            user_id=account.user_id,
            tier=account.entitlement_tier,
            computed_cost_usd=Decimal(usd),
            recorded_at=await db_now(db) - ago,
        )
    )
    await db.commit()


async def test_an_ordinary_account_is_not_stopped(db, funded_account):
    """The case that must never break. A ceiling that fires on real use is
    worse than no ceiling — it turns a paying customer away from the thing they
    paid for, and it would fire on the heaviest users first."""
    await _spent(db, funded_account, "0.50")

    session = await SessionService(db).start(user_id=funded_account.user_id)

    assert session is not None


async def test_a_room_is_refused_once_the_day_has_cost_enough(db, funded_account):
    ceiling = DAILY_SPEND_CEILING_USD[funded_account.entitlement_tier]
    await _spent(db, funded_account, str(ceiling))

    with pytest.raises(DailyCeilingReached):
        await SessionService(db).start(user_id=funded_account.user_id)


async def test_spend_outside_the_window_does_not_count(db, funded_account):
    """A rolling twenty-four hours rather than a calendar day.

    No timezone to decide, and no midnight at which somebody who has been
    hammering the API all evening is handed a fresh budget.
    """
    ceiling = DAILY_SPEND_CEILING_USD[funded_account.entitlement_tier]
    await _spent(db, funded_account, str(ceiling), ago=timedelta(hours=25))

    session = await SessionService(db).start(user_id=funded_account.user_id)

    assert session is not None


async def test_one_account_cannot_spend_another_out_of_a_room(db, funded_account):
    """Per account, which is also what keeps the write path shardable by
    `user_id` — `docs/deferred-scale-work.md` forbids a cross-user aggregate
    here, and this is not one."""
    stranger = Account(user_id=uuid.uuid4(), entitlement_tier="pro")
    db.add(stranger)
    await db.commit()
    await _spent(db, stranger, str(DAILY_SPEND_CEILING_USD["pro"] * 10))

    session = await SessionService(db).start(user_id=funded_account.user_id)

    assert session is not None


async def test_an_unpriced_room_does_not_bring_the_ceiling_down(db, funded_account):
    """Every row written before `computed_cost_usd` shipped has a null in it.

    Summing those as anything but zero would refuse rooms over spend nobody can
    account for — the exact opposite of what a cost control is for.
    """
    from app.core.database import db_now

    room = Session(
        user_id=funded_account.user_id,
        state=SessionState.SETTLED,
        settled_at=await db_now(db),
        end_reason=EndReason.USER_ENDED,
    )
    db.add(room)
    await db.flush()
    db.add(
        SessionCost(
            session_id=room.id,
            user_id=funded_account.user_id,
            tier=funded_account.entitlement_tier,
            computed_cost_usd=None,
        )
    )
    await db.commit()

    session = await SessionService(db).start(user_id=funded_account.user_id)

    assert session is not None


async def test_the_refusal_is_recorded(db, funded_account):
    """`CLAUDE.md` requires denials to be recorded, and this one doubly so: it
    fires on abuse but will occasionally fire on a heavy legitimate user, and
    the only way to learn which is to be able to look."""
    await _spent(
        db, funded_account, str(DAILY_SPEND_CEILING_USD[funded_account.entitlement_tier])
    )

    with pytest.raises(DailyCeilingReached):
        await SessionService(db).start(user_id=funded_account.user_id)

    denied = await db.scalars(
        select(AuditEvent).where(
            AuditEvent.event_type == AuditEventType.SESSION_START_DENIED
        )
    )
    reasons = [row.context.get("reason") for row in denied]
    assert "daily_ceiling_reached" in reasons


async def test_the_ceiling_scales_with_what_the_tier_can_legitimately_spend(db):
    """A free account holds fifteen minutes for *life* — about $0.68 of
    interrogation — so it can never legitimately approach a paid tier's day.
    One figure for everybody would have to be set high enough for Pro, which
    would leave free accounts with a ceiling they cannot reach by abuse either.
    """
    assert DAILY_SPEND_CEILING_USD["free"] < DAILY_SPEND_CEILING_USD["starter"]
    assert DAILY_SPEND_CEILING_USD["starter"] < DAILY_SPEND_CEILING_USD["pro"]


async def test_every_tier_has_a_ceiling(db):
    """A tier missing from the table would be a tier with no circuit breaker,
    and it would fail open rather than loudly."""
    from app.modules.billing.tiers import MONTHLY_ALLOWANCE_SECONDS

    for tier in {*MONTHLY_ALLOWANCE_SECONDS, "free"}:
        assert tier in DAILY_SPEND_CEILING_USD
