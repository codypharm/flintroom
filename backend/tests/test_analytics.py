"""First-party analytics — task #105, the architect's choice over a vendor.

An event is a name, a user and a time, and nothing else. No properties column,
deliberately: a JSON blob on an analytics row is where transcript text would
eventually leak into a table with a twelve-month lifetime, and every funnel
fact this product needs — rooms started, debriefs opened, sparring used — is
already in the domain tables. What those cannot answer is whether a person
*came back*, which is the one question `app_open` exists for.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.modules.analytics.models import AppEvent
from app.modules.analytics.service import AnalyticsService

from tests.conftest import create_funded_account

pytestmark = pytest.mark.asyncio


async def _events_of(db, user_id) -> list[AppEvent]:
    rows = await db.scalars(
        select(AppEvent).where(AppEvent.user_id == user_id).order_by(AppEvent.at)
    )
    return list(rows)


async def test_an_event_is_a_name_a_user_and_a_servers_clock(db, funded_account):
    await AnalyticsService(db).record(
        user_id=funded_account.user_id, names=["app_open"]
    )

    [event] = await _events_of(db, funded_account.user_id)
    assert event.name == "app_open"
    assert event.at is not None


async def test_the_endpoint_accepts_a_batch_and_answers_before_caring(
    client, funded_account, bearer, db
):
    """202, because the caller is a phone that must never wait on telemetry —
    the app fires and forgets, and the honest status is 'accepted'."""
    response = await client.post(
        "/v1/events",
        headers=bearer(funded_account.user_id),
        json={"events": [{"name": "app_open"}, {"name": "settings.viewed"}]},
    )

    assert response.status_code == 202
    names = [event.name for event in await _events_of(db, funded_account.user_id)]
    assert names == ["app_open", "settings.viewed"]


async def test_events_belong_to_the_credential_never_the_body(
    client, funded_account, bearer, db, ledger
):
    other = await create_funded_account(db, ledger)

    await client.post(
        "/v1/events",
        headers=bearer(funded_account.user_id),
        json={"events": [{"name": "app_open"}], "user_id": str(other.user_id)},
    )

    assert await _events_of(db, other.user_id) == []
    assert len(await _events_of(db, funded_account.user_id)) == 1


async def test_a_name_outside_the_shape_is_refused(client, funded_account, bearer, db):
    """The pattern is the whole defence against this table holding prose: a
    name is a slug, and anything that could carry a sentence is refused at
    the door rather than redacted later."""
    response = await client.post(
        "/v1/events",
        headers=bearer(funded_account.user_id),
        json={"events": [{"name": "I said our margin was seventy percent"}]},
    )

    assert response.status_code == 422
    assert await _events_of(db, funded_account.user_id) == []


async def test_an_unauthenticated_report_records_nothing(client, db):
    response = await client.post(
        "/v1/events", json={"events": [{"name": "app_open"}]}
    )

    assert response.status_code == 401


async def test_events_older_than_the_window_are_swept(db, funded_account):
    """Twelve months answers every retention curve worth drawing; older rows
    are behavioral personal data kept for no question anybody is asking —
    and the privacy policy now promises this number."""
    service = AnalyticsService(db)
    await service.record(user_id=funded_account.user_id, names=["app_open"])
    await db.execute(
        update(AppEvent)
        .where(AppEvent.user_id == funded_account.user_id)
        .values(at=func.now() - timedelta(days=400))
    )
    await service.record(user_id=funded_account.user_id, names=["app_open"])
    await db.commit()

    await service.sweep()

    assert len(await _events_of(db, funded_account.user_id)) == 1
