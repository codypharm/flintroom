"""The one route analytics has: the app reporting that moments happened."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import CurrentUser, rate_limit_user
from app.modules.auth.rate_limit import EVENT_REPORT_LIMIT
from app.modules.analytics.schemas import EventReport
from app.modules.analytics.service import AnalyticsService

router = APIRouter(tags=["analytics"])


@router.post(
    "/events",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit_user("event_report", EVENT_REPORT_LIMIT))],
)
async def report_events(
    body: EventReport,
    user_id: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Accept a batch of reported moments.

    The user comes from the credential, never the body — an events table a
    caller could attribute to somebody else would be a diary written by
    strangers. 202 with an empty body, because the caller is a phone that
    fires and forgets: telemetry must never be something a screen waits on,
    and there is nothing to say back about it.
    """
    await AnalyticsService(db).record(
        user_id=user_id, names=[event.name for event in body.events]
    )
    return Response(status_code=status.HTTP_202_ACCEPTED)
