"""How often one caller may knock.

Postgres rather than Redis, decided deliberately: only the auth and session-start
endpoints are limited, none of them is hot, and this product's concurrency is
bounded by provider cost long before a counter table is bothered. The interface
is narrow so that moving to Redis later is a swap — which is what makes deferring
it cheap rather than a bet.

In-process counting was the option ruled out rather than deferred. It is free,
and the limit then becomes per-worker: four processes is four times the limit,
and every deploy resets it. The threats here — credential stuffing, somebody
hammering session start to burn provider minutes — are exactly the ones that need
a count several processes agree on.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import db_now
from app.core.errors import RateLimited
from app.core.logging import get_logger
from app.modules.auth.models import RateLimitCounter

log = get_logger(__name__, tag="http")

#: Attempts per minute per caller.
#:
#: Generous, on purpose. Mobile users reach us through carrier NAT in large
#: groups, so an IP is often a whole town rather than a person — a tight limit
#: would lock out real users long before it inconvenienced anyone. What these
#: numbers stop is a script, not a determined attacker with a botnet, and that
#: is the honest bound on what any IP-keyed limit can do.
SIGN_IN_LIMIT = 20
REFRESH_LIMIT = 60
RATE_LIMIT_WINDOW = timedelta(minutes=1)

#: Rooms per minute per account. Far tighter than the numbers above, and it can
#: afford to be: the endpoint is authenticated, so the key is an account rather
#: than an address, and no honest client needs a second room in the same minute
#: — a user may only hold one at a time. What this bounds is a retry loop, and
#: every iteration of one is provider time on our invoice.
SESSION_START_LIMIT = 10

#: How long a finished window is kept before deletion.
#:
#: Not zero, and not "anything not current". A pass that deleted every window
#: but the live one would race a request that had just rolled over — and the
#: rows are worth nothing anyway, so an hour of slack costs a handful of rows
#: and removes the race entirely.
COUNTER_RETENTION = timedelta(hours=1)


def window_start_for(now: datetime, window: timedelta) -> datetime:
    """Floor a clock reading to the window it falls in.

    Derived rather than stored, so every process and every request agrees on
    where a window begins without coordinating about it.

    Module-level and directly tested because this is the part that ties a budget
    to the passage of time, and it is invisible from the outside: an
    implementation returning a constant behaves identically to a correct one in
    any test that ages a stored row by hand.
    """
    size = int(window.total_seconds())
    return datetime.fromtimestamp(int(now.timestamp()) // size * size, tz=now.tzinfo)


class RateLimiter(Protocol):
    """The whole contract. Deliberately this small — it is what makes the store
    replaceable without touching a single caller."""

    async def check(self, *, key: str, limit: int, window: timedelta) -> None: ...


class PostgresRateLimiter:
    """A fixed-window counter, incremented atomically."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def check(self, *, key: str, limit: int, window: timedelta) -> None:
        """Count this attempt and refuse it if the window is already full.

        Counted *before* the work rather than after, and counted whether or not
        the work succeeds. A limiter that only counts successes is no limiter at
        all on the paths that matter: guessing credentials produces nothing but
        failures, and each one would be free.
        """
        now = await db_now(self._db)
        window_start = window_start_for(now, window)

        # One statement, so the read-modify-write cannot interleave with another
        # request's. Doing this as SELECT-then-UPDATE would let concurrent
        # callers each read the same count and each decide they were under the
        # limit — which is precisely the case a limiter exists to stop.
        used = await self._db.scalar(
            text("""
            INSERT INTO rate_limit_counters (bucket_key, window_start, count)
            VALUES (:key, :window_start, 1)
            ON CONFLICT (bucket_key, window_start)
            DO UPDATE SET count = rate_limit_counters.count + 1
            RETURNING count
            """),
            {"key": key, "window_start": window_start},
        )
        # Committed immediately: the count has to survive the caller's
        # transaction rolling back, and on these paths it usually does — a
        # refused sign-in raises, and a rolled-back attempt that also forgets it
        # happened is an unlimited number of free attempts.
        await self._db.commit()

        if used > limit:
            retry_after = math.ceil((window_start + window - now).total_seconds())
            log.warning("rate_limited", bucket_key=key, limit=limit, used=used)
            raise RateLimited(
                retry_after_seconds=max(retry_after, 1), bucket_key=key, limit=limit
            )



    async def sweep(self) -> None:
        """Delete counters whose window is long past.

        Bounded by retention rather than by "everything but the current
        window". Deleting the live one would hand every caller a fresh budget on
        every pass — the counting would still be correct and nobody would ever
        stay limited, which is the kind of break that passes its own unit tests.
        """
        cutoff = await db_now(self._db) - COUNTER_RETENTION
        result = await self._db.execute(
            delete(RateLimitCounter).where(RateLimitCounter.window_start < cutoff)
        )
        await self._db.commit()

        if result.rowcount:
            log.info("rate_limit_counters_swept", deleted=result.rowcount)
