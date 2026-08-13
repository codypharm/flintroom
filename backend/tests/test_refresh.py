"""Refresh tokens — the part that makes a fifteen-minute session usable.

The access token is deliberately short-lived and unrevocable: nothing is looked
up to verify one, which is what keeps every authenticated request free of a
database round trip. That design only works if something else carries the long
session, and this is it.

Which makes the refresh token the more dangerous credential of the two. It lives
for weeks rather than minutes, so the tests that matter here are the ones about
what happens when one is stolen.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from app.core.errors import NotAuthenticated
from app.modules.auth.models import RefreshToken
from app.modules.auth.refresh import RefreshTokenService


@pytest_asyncio.fixture
async def refresh(db) -> RefreshTokenService:
    return RefreshTokenService(db)


async def test_a_refresh_token_can_be_exchanged_for_a_new_one(refresh, account):
    """The tracer: the app trades an old credential for a fresh pair.

    Rotation rather than reuse — a refresh token is spent when it is used. That
    is what makes theft detectable at all, and it is cheap to do here and
    impossible to retrofit once clients depend on a token that never changes.
    """
    issued = await refresh.issue(user_id=account.user_id)

    user_id, rotated = await refresh.rotate(token=issued)

    assert user_id == account.user_id
    assert rotated != issued


async def test_a_spent_token_is_refused(refresh, account):
    """Rotation means spent, not merely superseded.

    If an exchanged token kept working, rotation would be decoration: a thief
    who copied one keeps a working credential forever and nothing ever notices,
    which is the situation rotation exists to end.
    """
    issued = await refresh.issue(user_id=account.user_id)
    await refresh.rotate(token=issued)

    with pytest.raises(NotAuthenticated):
        await refresh.rotate(token=issued)


async def test_replaying_a_spent_token_ends_the_session_for_everyone(refresh, account):
    """Reuse detection, and the reason the family exists.

    Two parties now hold tokens descended from one sign-in, and we cannot tell
    which is the real user — the thief may have rotated first, leaving the
    victim holding the spent one. Guessing would lock out the wrong person half
    the time.

    So the session ends for both. The victim signs in again, which is a small
    cost; the alternative is leaving a thief with a live session on an account
    that has a payment method attached.

    This is the property the whole design is for, and it is the one that fails
    silently — everything still works from the user's side right up until it
    matters.
    """
    issued = await refresh.issue(user_id=account.user_id)
    _, rotated = await refresh.rotate(token=issued)

    with pytest.raises(NotAuthenticated):
        await refresh.rotate(token=issued)

    # The token the honest client is holding, killed by somebody else's replay.
    with pytest.raises(NotAuthenticated):
        await refresh.rotate(token=rotated)


async def test_an_expired_token_is_refused(refresh, account, db):
    """Sixty days is a bound, not a suggestion.

    Without this the only thing ending a session is the user signing out, and
    a token copied off a lost phone works until someone thinks to revoke it.
    """
    issued = await refresh.issue(user_id=account.user_id)
    await db.execute(
        update(RefreshToken).values(expires_at=func.now() - timedelta(days=1))
    )
    await db.commit()

    with pytest.raises(NotAuthenticated):
        await refresh.rotate(token=issued)


async def test_a_token_we_never_issued_is_refused(refresh):
    """The obvious one, which is also the one an attacker tries first."""
    with pytest.raises(NotAuthenticated):
        await refresh.rotate(token="not-a-token-we-ever-minted")


async def test_the_token_itself_is_never_stored(refresh, account, db):
    """A database dump must not be a pile of working credentials.

    Worth asserting rather than trusting the column name: this is the property
    that makes the table cheap to lose, and nothing else in the system would
    fail if it quietly stopped being true.
    """
    issued = await refresh.issue(user_id=account.user_id)

    stored = (await db.execute(select(RefreshToken.token_hash))).scalars().all()

    assert issued not in stored
    assert stored == [hashlib.sha256(issued.encode()).hexdigest()]


async def test_refreshing_over_http_returns_a_working_pair(client, google):
    """End to end: sign in, refresh, and the new access token opens a door.

    The refresh token changes too. A response that returned the same one would
    look identical to a client and quietly disable rotation — so it is asserted
    here rather than assumed from the service tests, because this is the layer
    the app actually talks to.
    """
    signed_in = await client.post(
        "/v1/auth/sessions",
        json={
            "provider": "google",
            "id_token": google.token_for(subject="g-1", email="dana@example.com"),
        },
    )
    original = signed_in.json()["refresh_token"]

    refreshed = await client.post(
        "/v1/auth/sessions/refresh", json={"refresh_token": original}
    )

    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != original

    identified = await client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
    )
    assert identified.status_code == 200


async def test_a_replayed_refresh_is_a_401_and_kills_the_session(client, google):
    """Reuse detection reaching the client, as a refused sign-in.

    401 rather than 403 or 409: the correct client response is to send the user
    back through sign-in, and that is the same instruction as for any other
    unusable credential. Nothing in the body says the session was killed for
    reuse — that would tell an attacker their replay was noticed.
    """
    signed_in = await client.post(
        "/v1/auth/sessions",
        json={
            "provider": "google",
            "id_token": google.token_for(subject="g-1", email="dana@example.com"),
        },
    )
    stolen = signed_in.json()["refresh_token"]

    honest = await client.post(
        "/v1/auth/sessions/refresh", json={"refresh_token": stolen}
    )
    replayed = await client.post(
        "/v1/auth/sessions/refresh", json={"refresh_token": stolen}
    )

    assert replayed.status_code == 401

    # And the honest client's fresh token died with it.
    after = await client.post(
        "/v1/auth/sessions/refresh",
        json={"refresh_token": honest.json()["refresh_token"]},
    )
    assert after.status_code == 401
