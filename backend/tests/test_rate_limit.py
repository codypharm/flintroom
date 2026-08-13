"""Rate limiting, on Postgres.

Redis is the textbook answer and was declined on purpose: only two endpoints are
limited, neither is hot, and this product's concurrency is capped by its own
economics long before a counter table is. The limiter sits behind a narrow
interface so that swapping the store is a swap rather than a rewrite — see
`docs/deferred-scale-work.md` for the signal that should reopen it.

A fixed window rather than a sliding log. It permits a burst of up to twice the
limit across a boundary, which is the honest cost; what it buys is one row per
key per window instead of one per request, on the only path where an attacker
controls the write rate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from app.core.errors import RateLimited
from app.modules.auth.models import RateLimitCounter
from app.modules.auth.rate_limit import (
    SIGN_IN_LIMIT,
    PostgresRateLimiter,
    window_start_for,
)

WINDOW = timedelta(minutes=1)


@pytest_asyncio.fixture
async def limiter(db) -> PostgresRateLimiter:
    return PostgresRateLimiter(db)


async def test_it_allows_up_to_the_limit_and_refuses_the_next(limiter):
    """The tracer, and both halves belong in one test.

    A limiter that refuses everything passes "the next one is refused" and is
    useless; one that allows everything passes "the first three are allowed"
    and is absent. Neither assertion means anything without the other.
    """
    for _ in range(3):
        await limiter.check(key="ip:198.51.100.7", limit=3, window=WINDOW)

    with pytest.raises(RateLimited):
        await limiter.check(key="ip:198.51.100.7", limit=3, window=WINDOW)


async def test_separate_keys_do_not_share_a_budget(limiter):
    """Otherwise the first noisy caller locks out everybody else.

    Which is not a hypothetical here: mobile users arrive through carrier NAT
    in large groups, so keys colliding by accident is the normal case rather
    than the adversarial one.
    """
    for _ in range(3):
        await limiter.check(key="ip:198.51.100.7", limit=3, window=WINDOW)

    await limiter.check(key="ip:203.0.113.9", limit=3, window=WINDOW)


async def test_the_budget_returns_when_the_window_does(limiter, db):
    """A limiter that never forgets is a ban.

    The failure this catches is a window computed once, or keyed on something
    that never advances — the caller is refused now and refused tomorrow, and
    nothing in the logs says why.

    Time is moved by ageing the stored counter rather than by freezing the
    process clock, because the window is derived from the *database's* clock.

    Note what this does and does not prove. It shows that a counter in a
    different window carries its own budget — but not that the window advances
    with the clock, because the row is aged by hand. An implementation whose
    window never moved would pass this. `window_start_for` is tested directly
    below for exactly that reason; this was found by mutation, not by review.
    """
    for _ in range(3):
        await limiter.check(key="ip:198.51.100.7", limit=3, window=WINDOW)

    with pytest.raises(RateLimited):
        await limiter.check(key="ip:198.51.100.7", limit=3, window=WINDOW)

    await db.execute(
        update(RateLimitCounter).values(
            window_start=RateLimitCounter.window_start - WINDOW
        )
    )
    await db.commit()

    await limiter.check(key="ip:198.51.100.7", limit=3, window=WINDOW)


async def test_repeated_sign_in_attempts_are_refused(client, google):
    """The endpoint this exists for.

    Sign-in is unauthenticated and reachable by anyone, which makes it the most
    exposed surface in the app. `CLAUDE.md` requires it limited.
    """
    token = google.token_for(subject="g-1", email="dana@example.com")

    statuses = [
        (
            await client.post(
                "/v1/auth/sessions", json={"provider": "google", "id_token": token}
            )
        ).status_code
        for _ in range(SIGN_IN_LIMIT + 1)
    ]

    assert statuses[:SIGN_IN_LIMIT] == [200] * SIGN_IN_LIMIT
    assert statuses[-1] == 429


async def test_failed_attempts_are_counted_too(client):
    """The whole point, and the easy thing to get wrong.

    Guessing credentials produces nothing but failures. A limiter that only
    counted successes would leave exactly the attack it exists to stop entirely
    unmetered, while looking like it worked in every test that used a valid
    token.
    """
    rejected = [
        (
            await client.post(
                "/v1/auth/sessions",
                json={"provider": "google", "id_token": f"guess-{attempt}"},
            )
        ).status_code
        for attempt in range(SIGN_IN_LIMIT + 1)
    ]

    assert rejected[:SIGN_IN_LIMIT] == [401] * SIGN_IN_LIMIT
    assert rejected[-1] == 429


async def test_a_limited_response_says_how_long_to_wait(client):
    """Without `Retry-After` a client either gives up or retries immediately.

    Both are worse for us than one that waits: the second turns a rate limit
    into a hot loop against the endpoint we were trying to protect.
    """
    for attempt in range(SIGN_IN_LIMIT + 1):
        response = await client.post(
            "/v1/auth/sessions",
            json={"provider": "google", "id_token": f"guess-{attempt}"},
        )

    assert response.status_code == 429
    assert 0 < int(response.headers["Retry-After"]) <= 60
    # Nothing about which limit, how much budget is left, or how many others
    # share the key — that is a map of our defences.
    assert response.json()["error"] == {
        "code": "rate_limited",
        "message": "Too many attempts. Please wait a moment and try again.",
    }


def test_the_window_advances_with_the_clock():
    """The arithmetic that ties a budget to time, tested where it is visible.

    Every other test here ages a row by hand, so all of them pass against an
    implementation that returns a constant — which is to say, against a limiter
    whose window never ends and whose first burst bans a caller forever.

    Two properties, and both are needed: readings inside one window agree, and a
    reading a window later does not.
    """
    window = timedelta(minutes=1)
    start = datetime(2026, 8, 13, 9, 0, 0, tzinfo=UTC)

    assert window_start_for(start, window) == window_start_for(
        start + timedelta(seconds=59), window
    )
    assert (
        window_start_for(start + window, window) - window_start_for(start, window)
    ) == window


async def test_the_sweep_clears_windows_that_have_passed(limiter, db):
    """Counters accumulate one row per key per minute and nothing removed them.

    Cheap to delete because the rows are disposable: losing one costs a moment
    of unmetered attempts and nothing a user owns.
    """
    await limiter.check(key="ip:198.51.100.7", limit=3, window=WINDOW)
    await db.execute(
        update(RateLimitCounter).values(
            window_start=RateLimitCounter.window_start - timedelta(hours=2)
        )
    )
    await db.commit()

    await limiter.sweep()

    assert await _counter_count(db) == 0


async def test_the_sweep_leaves_the_live_window_alone(limiter, db):
    """Otherwise the sweep is an attacker's best friend.

    Deleting the current window resets every caller's budget each time the loop
    runs. The limiter would still pass every test above — the counting works —
    while in production nobody is ever limited for longer than one pass.
    """
    for _ in range(3):
        await limiter.check(key="ip:198.51.100.7", limit=3, window=WINDOW)

    await limiter.sweep()

    with pytest.raises(RateLimited):
        await limiter.check(key="ip:198.51.100.7", limit=3, window=WINDOW)


async def _counter_count(db) -> int:
    return (
        await db.execute(select(func.count()).select_from(RateLimitCounter))
    ).scalar_one()
