"""Turning a verified provider identity into a Flintroom user.

`OidcVerifier` decides whether a sign-in is genuine and is proven separately;
these tests take that as given and cover what happens next — which account the
person lands in. That is the decision with money attached, because
`docs/onboarding.md` grants 15 lifetime minutes per `user_id`.

The verifier is stubbed here for the same reason the JWKS transport was stubbed
there: this file is about identity resolution, and a test that also re-proves
RS256 tells you less about both.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.errors import NotAuthenticated
from app.modules.auth.service import AuthService
from app.modules.billing.models import Account


async def test_a_first_sign_in_creates_an_account(auth, google, db):
    """The tracer.

    An account is created here rather than lazily on first session, because
    everything downstream — the ledger, sessions, the free grant — is keyed on
    a `user_id` that has an `accounts` row. A user who signed in but has no
    account is a state with no correct handling anywhere.
    """
    token = google.token_for(subject="google-1", email="dana@example.com")

    user_id = await auth.sign_in(provider="google", id_token=token)

    account = await db.get(Account, user_id)
    assert account is not None
    assert account.entitlement_tier == "free"
    assert isinstance(user_id, uuid.UUID)


async def test_signing_in_again_returns_the_same_user(auth, google, db):
    """Sign-in is a lookup that sometimes creates, not a creation.

    Every subsequent launch of the app hits this path. If it minted a new
    account each time, a user would lose their minutes and their history on
    every sign-in — and `docs/onboarding.md` grants 15 lifetime minutes per
    `user_id`, so it would also hand out free time without limit.
    """
    token = google.token_for(subject="google-1", email="dana@example.com")

    first = await auth.sign_in(provider="google", id_token=token)
    second = await auth.sign_in(provider="google", id_token=token)

    assert first == second
    assert await _account_count(db) == 1


async def test_a_second_provider_with_the_same_verified_email_is_the_same_user(
    auth, google, apple, db
):
    """The decision from `docs/onboarding.md`, and it is a money decision.

    Two accounts means two 15-minute lifetime grants — real provider cost, and
    Open Risk #4 makes every per-minute assumption load-bearing. The common
    case is not abuse though: it is someone who genuinely cannot remember which
    button they pressed last week, opening the app the night before a board
    review to find their minutes and their history gone.
    """
    signed_up = await auth.sign_in(
        provider="google",
        id_token=google.token_for(subject="google-1", email="dana@example.com"),
    )

    returned = await auth.sign_in(
        provider="apple",
        id_token=apple.token_for(subject="apple-1", email="dana@example.com"),
    )

    assert returned == signed_up
    assert await _account_count(db) == 1


async def test_an_unverified_email_never_links(auth, google, apple, db):
    """The rule that keeps linking from being an account takeover.

    Linking on an address nobody vouched for means anyone who can obtain a
    token asserting `dana@example.com` inherits Dana's account — her sessions,
    her minutes, her transcripts. The provider's `email_verified` flag is the
    entire basis for believing the address, so without it there is no claim to
    act on.

    Costing us a duplicate account is the correct trade. `docs/onboarding.md`
    is explicit: never link on an unverified email, ever.
    """
    dana = await auth.sign_in(
        provider="google",
        id_token=google.token_for(subject="google-1", email="dana@example.com"),
    )

    claimant = await auth.sign_in(
        provider="apple",
        id_token=apple.token_for(
            subject="apple-impostor", email="dana@example.com", email_verified=False
        ),
    )

    assert claimant != dana
    assert await _account_count(db) == 2


async def test_a_relay_address_starts_its_own_account(auth, google, apple, db):
    """Apple's Hide My Email is the known hole in linking, stated out loud.

    The relay address is stable for this person and this app, so it works
    perfectly as an identity — it simply will never match the Google one. That
    user ends up with two accounts and two free grants, and the fix is an
    explicit "connect another sign-in" flow later, not a cleverer guess now.

    Asserted rather than merely documented, so the limitation is visible to
    whoever next reads this file wondering why linking "does not work".
    """
    await auth.sign_in(
        provider="google",
        id_token=google.token_for(subject="google-1", email="dana@example.com"),
    )

    relayed = await auth.sign_in(
        provider="apple",
        id_token=apple.token_for(
            subject="apple-1", email="xyz@privaterelay.appleid.com"
        ),
    )

    assert await _account_count(db) == 2
    assert relayed is not None


async def test_devices_racing_a_first_sign_in_produce_one_account(engine, db, google):
    """Two devices, one new user, one account — and no 500.

    Not hypothetical: onboarding ends with sign-in, and a user who taps twice
    on a slow connection, or has the phone and the iPad open, races themselves.
    The service-level lookup cannot see an uncommitted sibling transaction, so
    every racer finds no identity and every racer decides to create one. Only
    the unique constraint can arbitrate.

    `CLAUDE.md` is explicit that a duplicate action is never a 500. Here it must
    be entirely invisible: the loser re-reads the row the winner just wrote and
    returns the same user. The alternative — a crash on the last screen of
    onboarding — is the worst possible moment for one.

    Five racers and pre-warmed connections, for the reasons the equivalent
    session test documents: a cold pool serialises the racers and the test then
    passes without ever reproducing the race.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    racers = [factory() for _ in range(5)]
    await asyncio.gather(*(session.execute(text("SELECT 1")) for session in racers))

    token = google.token_for(subject="google-1", email="dana@example.com")
    gate = asyncio.Event()

    async def sign_in_once(session):
        await gate.wait()
        return await AuthService(session, verifiers={"google": google}).sign_in(
            provider="google", id_token=token
        )

    tasks = [asyncio.create_task(sign_in_once(session)) for session in racers]
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(*tasks)

    for session in racers:
        await session.close()

    assert len(set(results)) == 1
    assert await _account_count(db) == 1


async def test_a_provider_we_do_not_offer_is_refused(auth):
    """Not a 404. Answering "we do not support that one" enumerates our setup."""
    with pytest.raises(NotAuthenticated):
        await auth.sign_in(provider="facebook", id_token="anything")


async def test_signing_in_over_http_returns_a_token_that_works(client, google, db):
    """End to end: a provider token in, a credential out, and it opens a door.

    Asserted by *using* the access token rather than by inspecting it. A
    response containing a plausible-looking string proves nothing — the only
    property that matters is that the next request is authenticated as the
    right user, which is what the app will actually do with it.
    """
    token = google.token_for(subject="google-1", email="dana@example.com")

    signed_in = await client.post(
        "/v1/auth/sessions", json={"provider": "google", "id_token": token}
    )

    assert signed_in.status_code == 200
    access_token = signed_in.json()["access_token"]

    identified = await client.get(
        "/v1/me", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert identified.status_code == 200
    assert identified.json()["user_id"] == str(await _only_account(db))


async def test_a_rejected_provider_token_never_reaches_the_database(client, db):
    """A refused sign-in creates nothing.

    The account is created by the sign-in path, so a verification failure that
    still wrote a row would let anyone mint accounts — and each one carries a
    15-minute grant once that lands.
    """
    refused = await client.post(
        "/v1/auth/sessions",
        json={"provider": "google", "id_token": "not-a-token-we-issued"},
    )

    assert refused.status_code == 401
    assert await _account_count(db) == 0


async def test_a_malformed_sign_in_is_rejected_before_any_work(client):
    """Pydantic, per `CLAUDE.md` — no raw dict access at the router."""
    response = await client.post("/v1/auth/sessions", json={"provider": "google"})

    assert response.status_code == 422


async def _only_account(db) -> uuid.UUID:
    return (await db.execute(select(Account.user_id))).scalar_one()


async def _account_count(db) -> int:
    return (
        await db.execute(select(func.count()).select_from(Account))
    ).scalar_one()
