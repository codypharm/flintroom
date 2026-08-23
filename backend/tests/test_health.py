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
