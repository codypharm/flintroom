"""The session lifecycle, over HTTP.

The service and the meter have been exercised directly since the beginning;
this is the first time either is reachable from outside the process. What these
tests add on top of `test_sessions.py` is everything the transport introduces:
who is calling, whether they own what they are touching, and what a refusal
looks like on the wire.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.modules.auth.tokens import AccessTokens
from app.modules.sessions.models import Session as SessionModel
from app.modules.sessions.schemas import EndReason, SessionState

from tests.conftest import SECRET, create_funded_account


@pytest.fixture
def bearer():
    """Headers that authenticate as a given user.

    Minted rather than obtained by signing in: these tests are about sessions,
    and routing every one of them through the provider stub would make a
    sign-in regression fail here too, in a module that has nothing to say
    about it.
    """

    def headers(user_id: uuid.UUID) -> dict[str, str]:
        token = AccessTokens(secret=SECRET).issue(user_id=user_id)
        return {"Authorization": f"Bearer {token}"}

    return headers


async def test_starting_a_room_opens_one_for_the_caller(
    client, funded_account, bearer
):
    """The tracer: an authenticated POST puts the caller in `provisioning`.

    Not `active`. The room is not open until the voice channel is up, and that
    is the server's observation to make — a client that could declare itself
    active would start the meter on a room that may never exist.
    """
    response = await client.post("/v1/sessions", headers=bearer(funded_account.user_id))

    assert response.status_code == 201
    body = response.json()
    assert body["state"] == SessionState.PROVISIONING.value
    assert body["user_id"] == str(funded_account.user_id)


async def test_starting_a_room_without_a_credential_opens_nothing(client, db):
    """The most expensive endpoint in the product is the one worth checking.

    A room costs provider minutes from the moment it opens, so an unauthenticated
    start is not merely a data leak — it is an invoice anyone on the internet
    can generate. Asserted on the database as well as the status: a 401 returned
    after the row was written is the failure that matters.
    """
    response = await client.post("/v1/sessions")

    assert response.status_code == 401
    assert await _session_count(db) == 0


async def test_a_caller_can_read_the_room_they_are_in(client, funded_account, bearer):
    """What the client polls while the panel spins up.

    `provisioning` is a real wait — agent spin-up takes seconds and can fail —
    so the client needs somewhere to ask whether the room opened.
    """
    headers = bearer(funded_account.user_id)
    started = (await client.post("/v1/sessions", headers=headers)).json()

    response = await client.get(f"/v1/sessions/{started['id']}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == started["id"]


async def test_one_user_cannot_read_another_users_room(
    client, funded_account, bearer, db, ledger
):
    """A session id in a URL is not a capability.

    404 rather than 403, deliberately. A 403 confirms the session exists, which
    turns this endpoint into an oracle for guessing ids — and there is nothing
    to gain by distinguishing the two, since a caller who does not own it has
    the same next move either way.
    """
    stranger = await create_funded_account(db, ledger)
    theirs = (
        await client.post("/v1/sessions", headers=bearer(stranger.user_id))
    ).json()

    response = await client.get(
        f"/v1/sessions/{theirs['id']}", headers=bearer(funded_account.user_id)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


async def test_a_second_room_is_refused_while_one_is_running(
    client, funded_account, bearer, db
):
    """One room at a time, and the client is told which rule it hit.

    409 rather than 200-with-the-existing-session: the two devices tapping
    Start want different rooms, and silently handing back the first one would
    have the second device streaming audio into a session the first is already
    using.
    """
    headers = bearer(funded_account.user_id)
    await client.post("/v1/sessions", headers=headers)

    response = await client.post("/v1/sessions", headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "active_session_exists"
    assert await _session_count(db) == 1


async def test_a_caller_with_no_minutes_is_refused_at_the_door(
    client, account, bearer, db
):
    """The only moment the answer can be no.

    `account` rather than `funded_account`: an empty ledger is the state a user
    reaches by spending everything, and §4.5 puts the refusal here — at the
    door — because it is forbidden anywhere after the room opens.
    """
    response = await client.post("/v1/sessions", headers=bearer(account.user_id))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_minutes_remaining"
    assert await _session_count(db) == 0


async def test_ending_a_room_closes_billing_and_releases_the_lock(
    client, funded_account, bearer, sessions
):
    """The End button, which sends an intent the server decides on.

    Settled in the same request rather than left `finalizing` for the reaper.
    That matters to the user rather than to the books: the lock releases now, so
    the debrief they are being handed to can start immediately, and §4.1 puts
    settlement before the coaching phases.
    """
    headers = bearer(funded_account.user_id)
    started = (await client.post("/v1/sessions", headers=headers)).json()
    # Server-side in production: the room is open once the voice channel is up,
    # which is not something a client is trusted to declare.
    await sessions.activate(session_id=uuid.UUID(started["id"]))

    response = await client.post(f"/v1/sessions/{started['id']}/end", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == SessionState.SETTLED.value
    assert body["end_reason"] == EndReason.USER_ENDED.value

    # The lock is gone: the next room opens without a 409.
    assert (await client.post("/v1/sessions", headers=headers)).status_code == 201


async def _session_count(db) -> int:
    return (
        await db.execute(select(func.count()).select_from(SessionModel))
    ).scalar_one()
