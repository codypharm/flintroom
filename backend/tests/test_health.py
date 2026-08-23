"""The one route a load balancer may call.

Railway restarts a container whose healthcheck fails, so this is liveness and
nothing more: no database, no providers, no auth. A healthcheck that touches
the database turns a database blip into a restart storm on top of it, and one
that needs a token cannot be called by the thing that needs to call it.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_health_answers_without_auth_or_database() -> None:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        answered = await client.get("/health")

    assert answered.status_code == 200
    assert answered.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /health/sweeps — the alert surface for sweep silence.
#
# The sweep loop's failure mode is silence: when it dies, nothing bills while
# the voice provider keeps charging, and no error fires anywhere
# (`sessions/runner.py` — "an alert on its absence is the thing that makes
# this design safe"). This endpoint turns that absence into a status code an
# external monitor can watch. Deliberately separate from /health: Railway
# restarts on a failing /health, and restarting the API does not revive a
# database, so a blip would become a restart storm on top of it.
# ---------------------------------------------------------------------------

from app.modules.sessions.runner import METER_SILENCE_LIMIT, SweepRunner


def _no_sessions():
    raise AssertionError("the check must not touch the database")


async def _sweeps_health(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get("/health/sweeps")


@pytest.mark.asyncio
async def test_sweeps_health_fails_when_the_process_runs_no_sweeps() -> None:
    """No runner is the loudest kind of silence, not an excuse for a 200."""
    app = create_app()

    answered = await _sweeps_health(app)

    assert answered.status_code == 500


@pytest.mark.asyncio
async def test_sweeps_health_is_ok_while_the_meter_was_heard_recently() -> None:
    now = [0.0]
    app = create_app()
    app.state.sweep_runner = SweepRunner(_no_sessions, clock=lambda: now[0])

    # Construction counts as the first heartbeat, so a booting process gets
    # the full limit to complete its first pass rather than alarming at zero.
    now[0] = METER_SILENCE_LIMIT.total_seconds() - 1

    answered = await _sweeps_health(app)

    assert answered.status_code == 200
    assert answered.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_sweeps_health_turns_meter_silence_into_a_failing_check() -> None:
    now = [0.0]
    app = create_app()
    app.state.sweep_runner = SweepRunner(_no_sessions, clock=lambda: now[0])

    now[0] = METER_SILENCE_LIMIT.total_seconds() + 1

    answered = await _sweeps_health(app)

    assert answered.status_code == 500
    assert answered.json()["status"] == "silent"
