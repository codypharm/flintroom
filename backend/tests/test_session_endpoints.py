"""The session lifecycle, over HTTP.

The service and the meter have been exercised directly since the beginning;
this is the first time either is reachable from outside the process. What these
tests add on top of `test_sessions.py` is everything the transport introduces:
who is calling, whether they own what they are touching, and what a refusal
looks like on the wire.
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from sqlalchemy import func, select

from app.modules.auth.rate_limit import SESSION_START_LIMIT
from app.modules.sessions.models import Session as SessionModel
from app.modules.sessions.schemas import EndReason, SessionState
from app.modules.voice.tickets import VoiceTicketService

from tests.conftest import create_funded_account


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


async def test_hammering_start_is_refused(client, funded_account, bearer):
    """`CLAUDE.md` requires session start rate limited, and this is why.

    Every room that opens is provider time on our invoice, so a client stuck in
    a retry loop is a cost incident rather than a nuisance. The refusals in
    between are counted too — a limiter that only counted the rooms that opened
    would never fire here, because after the first one every attempt is a 409.

    Twice the budget, and the 429 is looked for anywhere rather than at the end.
    The limiter's window is fixed and floored off the database clock, so a loop
    of exactly `limit + 1` attempts that happens to straddle a minute boundary
    starts counting again from one and the last attempt comes back 409 — which
    is what this asserted, and it failed once in a full-suite run for exactly
    that reason. Twice the budget cannot be split so that neither half fills.
    """
    headers = bearer(funded_account.user_id)

    statuses = [
        (await client.post("/v1/sessions", headers=headers)).status_code
        for _ in range(SESSION_START_LIMIT * 2 + 1)
    ]

    assert statuses[0] == 201
    assert 429 in statuses


async def test_one_user_hammering_start_does_not_lock_out_another(
    client, funded_account, bearer, db, ledger
):
    """The budget is per account, not per address.

    Keyed on the authenticated user rather than the socket, which the
    unauthenticated endpoints cannot do. It is the better key on both sides:
    mobile users share carrier NAT in large groups, so an address is often a
    whole town, and a signed-in identity cannot be swapped for a fresh one the
    way an address can.
    """
    for _ in range(SESSION_START_LIMIT + 1):
        await client.post("/v1/sessions", headers=bearer(funded_account.user_id))

    bystander = await create_funded_account(db, ledger)

    response = await client.post("/v1/sessions", headers=bearer(bystander.user_id))

    assert response.status_code == 201


async def _session_count(db) -> int:
    return (
        await db.execute(select(func.count()).select_from(SessionModel))
    ).scalar_one()


async def test_starting_a_room_returns_a_ticket_that_opens_its_stream(
    client, db, funded_account, bearer
):
    """The one response that carries a ticket, because it is the only one that should.

    Deliberately not on `SessionRead`: reading a session or ending one must not
    mint a credential, and sharing a schema is how that would happen by
    accident rather than by decision.

    Asserted by spending the ticket rather than by matching its shape. A test
    that only checked a string was present would still pass if the endpoint
    returned one minted for a different room.
    """
    response = await client.post("/v1/sessions", headers=bearer(funded_account.user_id))

    assert response.status_code == 201
    body = response.json()

    holder = await VoiceTicketService(db).redeem(
        ticket=body["stream_ticket"], session_id=uuid.UUID(body["id"])
    )
    assert holder == funded_account.user_id


# ---------------------------------------------------------------------------
# Re-minting a stream ticket — the resume path's front door.
# docs/reconnect.md decision 3: a fresh single-use ticket for any live room
# of the caller's, gated on ownership and liveness and nothing else — not on
# the disconnect stamp, because the fastest reconnections arrive before the
# server has noticed the old socket died.
# ---------------------------------------------------------------------------


async def test_a_live_room_re_mints_a_key_to_its_own_stream(
    client, funded_account, bearer, db, sessions
):
    headers = bearer(funded_account.user_id)
    started = (await client.post("/v1/sessions", headers=headers)).json()
    await sessions.connection_opened(
        session_id=uuid.UUID(started["id"]), connection_id=uuid.uuid4()
    )

    response = await client.post(
        f"/v1/sessions/{started['id']}/stream-ticket", headers=headers
    )

    assert response.status_code == 200
    ticket = response.json()["stream_ticket"]
    # The proof that matters: the socket's own gatekeeper accepts it.
    redeemed = await VoiceTicketService(db).redeem(
        ticket=ticket, session_id=uuid.UUID(started["id"])
    )
    assert redeemed == funded_account.user_id


async def test_a_room_that_is_not_live_re_mints_nothing(
    client, funded_account, bearer
):
    """Provisioning has the start's own ticket; settled has no stream at all.
    Either way there is no live room to rejoin, and saying so is a business
    refusal rather than a mystery."""
    headers = bearer(funded_account.user_id)
    started = (await client.post("/v1/sessions", headers=headers)).json()

    response = await client.post(
        f"/v1/sessions/{started['id']}/stream-ticket", headers=headers
    )

    assert response.status_code == 422


async def test_one_user_cannot_re_mint_into_anothers_room(
    client, funded_account, bearer, db, ledger, sessions
):
    headers = bearer(funded_account.user_id)
    started = (await client.post("/v1/sessions", headers=headers)).json()
    await sessions.connection_opened(
        session_id=uuid.UUID(started["id"]), connection_id=uuid.uuid4()
    )
    other = await create_funded_account(db, ledger)

    response = await client.post(
        f"/v1/sessions/{started['id']}/stream-ticket",
        headers=bearer(other.user_id),
    )

    assert response.status_code == 404


async def test_re_minting_without_a_credential_is_refused(client, funded_account, bearer):
    headers = bearer(funded_account.user_id)
    started = (await client.post("/v1/sessions", headers=headers)).json()

    response = await client.post(f"/v1/sessions/{started['id']}/stream-ticket")

    assert response.status_code == 401
