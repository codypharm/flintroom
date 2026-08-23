"""Recording what the app reports, and forgetting it on schedule.

First-party by the architect's choice (#105): the events land in the same
Postgres everything else lives in, viewed with SQL rather than a vendor
dashboard — `docs/analytics.md` carries the queries. No third-party SDK on
the phone, no new data processor in the privacy policy, no bill.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import rows_touched
from app.core.logging import get_logger
from app.modules.analytics.models import AppEvent

log = get_logger(__name__, tag="analytics")

#: How long an event may live. Twelve months draws every retention curve
#: worth drawing; older rows are behavioral personal data kept for no
#: question anybody is asking — and `docs/privacy-policy.md` promises this
#: number, so moving it moves the disclosure.
EVENT_RETENTION = timedelta(days=365)


class AnalyticsService:
    """Writes reported events, and sweeps the ones past their window."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def record(self, *, user_id: uuid.UUID, names: list[str]) -> None:
        """Keep a batch, stamped with the server's clock.

        No dedup and no idempotency key, deliberately: a double-flushed
        `app_open` inflates nothing anyone reads (retention asks *whether* a
        day has events, not how many), and an idempotency scheme would be
        more machinery than the whole feature.
        """
        for name in names:
            self._db.add(AppEvent(user_id=user_id, name=name))
        await self._db.commit()

    async def sweep(self) -> None:
        """Forget events older than the promised window.

        One line per pass like every sweep on the loop, because the absence
        of deletions and the absence of the sweep look identical from the
        table — see `docs/deployment.md`.
        """
        swept = await self._db.execute(
            delete(AppEvent).where(AppEvent.at < func.now() - EVENT_RETENTION)
        )
        await self._db.commit()
        log.info("app_events_swept", deleted=rows_touched(swept))
