"""Deleting an account over HTTP.

`AccountDeletion` has been exercised directly since the service was written;
this is the first time a phone can reach it, and it is the piece Apple actually
requires — a deletion path that exists in the backend and not in the app is not
in-app deletion.

What the transport adds is who is asking. Everything else about the flow is the
service's, and is not re-tested here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.modules.auth.refresh import RefreshTokenService
from app.modules.billing.deletion import WINDOW
from app.modules.billing.models import Account


async def test_a_user_can_schedule_their_own_deletion(client, db, funded_account, bearer):
    """The tracer, and the store blocker.

    Apple has required in-app account deletion since 2022 for any app that
    supports account creation, and `docs/privacy-policy.md` cannot be published
    while it claims a control nothing implements.

    The response carries when it happens rather than only that it was accepted.
    The window is the architect's choice and it is recoverable, so a user who
    is not told the date cannot use the thing the window is for.
    """
    user_id = funded_account.user_id

    response = await client.request(
        "DELETE", "/v1/me", headers=bearer(user_id)
    )

    assert response.status_code == 202
    purge_at = datetime.fromisoformat(response.json()["purge_at"])
    requested = await _requested_at(db, user_id)
    assert purge_at == requested + WINDOW


async def test_asking_twice_returns_the_same_date_rather_than_a_later_one(
    client, funded_account, bearer
):
    """Idempotent on the wire, and the harm is specific.

    A client that retries on a flaky connection, or a user who taps again
    because nothing visibly happened, must not push the purge back a further
    seven days each time — that is a deletion which recedes from the person who
    asked for it. A 409 would be the other way to say this and would be worse:
    the app would have to treat "already scheduled" as an error state, on the
    one screen where a confusing answer costs the user their trust.
    """
    first = await client.request("DELETE", "/v1/me", headers=bearer(funded_account.user_id))
    again = await client.request("DELETE", "/v1/me", headers=bearer(funded_account.user_id))

    assert again.status_code == 202
    assert again.json() == first.json()


async def test_an_unauthenticated_caller_deletes_nothing(client):
    """401, and it is the only sensible answer.

    There is no body on this request and no identifier in the path — the
    account being destroyed is entirely determined by the credential. An
    endpoint that read a user from anywhere else would be one where a caller
    chooses whose account goes.
    """
    assert (await client.request("DELETE", "/v1/me")).status_code == 401


async def test_the_request_signs_the_caller_out_everywhere(
    client, db, funded_account, bearer
):
    """`docs/account-deletion.md`: revoked at request time, not at purge.

    Asserted here as well as against the service because this is the path a
    real user takes, and the property is about a credential rather than a row:
    the window is seven days long, and a token left alive spans all of it on an
    account that is still fully usable.
    """
    token = await RefreshTokenService(db).issue(user_id=funded_account.user_id)

    await client.request("DELETE", "/v1/me", headers=bearer(funded_account.user_id))

    refreshed = await client.post(
        "/v1/auth/sessions/refresh", json={"refresh_token": token}
    )
    assert refreshed.status_code == 401


async def _requested_at(db, user_id) -> datetime | None:
    rows = await db.execute(
        select(Account.deletion_requested_at).where(Account.user_id == user_id)
    )
    return rows.scalar_one()


async def test_signing_in_calls_the_deletion_off_and_says_so(
    client, db, funded_account, google
):
    """`docs/account-deletion.md` decision 5, and the message is the load-bearing half.

    An account that quietly un-deletes itself is worse than one that stayed
    deleted, because the user never learns their data is still there. The wire
    carries the fact and the app carries the sentence — copy belongs to the
    client, but it cannot write a sentence about something nobody told it.

    A boolean about *this* sign-in rather than a field on `GET /me`, because it
    is an event and not a state: a moment later there is no pending deletion to
    report, and the one chance to say what happened has gone.
    """
    token = google.token_for(subject="google-77", email="dana@example.com")
    signed_up = await client.post(
        "/v1/auth/sessions", json={"provider": "google", "id_token": token}
    )
    assert signed_up.json()["deletion_cancelled"] is False

    user_id = (
        await client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {signed_up.json()['access_token']}"},
        )
    ).json()["user_id"]
    await client.request(
        "DELETE",
        "/v1/me",
        headers={"Authorization": f"Bearer {signed_up.json()['access_token']}"},
    )

    back = await client.post(
        "/v1/auth/sessions", json={"provider": "google", "id_token": token}
    )

    assert back.status_code == 200
    assert back.json()["deletion_cancelled"] is True
    assert await _requested_at(db, uuid.UUID(user_id)) is None
