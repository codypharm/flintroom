"""Answering the survey after signing in, rather than before.

**A reordering the architect made on 2026-08-20**, and it reverses part of
`docs/onboarding.md`. That document settled *survey first, sign-in after* —
"identity is asked for once there is something to lose… rather than a toll gate
in front of a stranger" — and the survey has ridden on the sign-in request ever
since, in one call, because "a partially-created account with no configuration
is a state worth not having".

What changed is the case that argument never considered: a **signed-out** launch
(#86). A returning user is not a stranger and has nothing to lose by signing in
— they have something to recover — and survey-first leaves them no way in at
all. The old order also had a cost the document itself named: somebody who
abandons at the sign-in sheet "leaves having answered five questions and seen
nothing", and five answers cannot be recovered while an unconfigured account can
simply be asked again.

So the state that document refuses is now reachable, deliberately, and these
tests are what keep it survivable: an account with no answers works, says so,
and can answer later.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.modules.onboarding.models import Situation
from app.modules.sessions.models import UserPreference

from tests.conftest import create_funded_account

PLAN = {
    "situation": "board_review",
    "happens_on": "2026-09-01",
    "role": "exec",
    "audience": ["budget", "rival"],
}


async def test_an_account_can_answer_the_survey_after_it_exists(
    client, db, funded_account, bearer
):
    """The tracer for the new order. Sign in first, describe the room after.

    Both halves land, because they are one answer: the durable part — role and
    audience — on `user_preferences`, and the occasion on `situations`. The
    service already wrote them in one transaction for the sign-in path; this
    gives that the door it never had.
    """
    response = await client.post(
        "/v1/onboarding", json=PLAN, headers=bearer(funded_account.user_id)
    )

    assert response.status_code == 204

    kept = await db.scalar(
        select(UserPreference).where(UserPreference.user_id == funded_account.user_id)
    )
    assert kept is not None and kept.presenter_role == "exec"

    assert await db.scalar(
        select(func.count())
        .select_from(Situation)
        .where(Situation.user_id == funded_account.user_id)
    ) == 1


async def test_an_account_that_has_not_answered_says_so(client, funded_account, bearer):
    """What the launch gate reads to decide whether to ask.

    On `/v1/me` rather than an endpoint of its own. That call already exists for
    exactly this moment — its docstring says "the mobile client calls this on
    launch" — and answering "who are you" and "have you told us anything" in one
    round trip is one round trip on the slowest screen in the product.
    """
    response = await client.get("/v1/me", headers=bearer(funded_account.user_id))

    assert response.status_code == 200
    assert response.json()["onboarded"] is False


async def test_an_account_that_has_answered_is_not_asked_again(
    client, funded_account, bearer
):
    """Keyed to the account, not the install.

    A reinstall is the moment a returning user most needs to be left alone, and
    a local flag is exactly what a reinstall destroys. The server knows, so the
    server answers.
    """
    headers = bearer(funded_account.user_id)
    await client.post("/v1/onboarding", json=PLAN, headers=headers)

    assert (await client.get("/v1/me", headers=headers)).json()["onboarded"] is True


async def test_answering_twice_does_not_duplicate_the_account_s_preferences(
    client, db, funded_account, bearer
):
    """A retry is a retry, not a second person.

    The preferences upsert and the situation appends — a second meeting is a
    second occasion rather than a correction of the first — which is the
    service's existing rule, asserted here because a client that can be
    re-opened mid-survey will send this twice.
    """
    headers = bearer(funded_account.user_id)

    await client.post("/v1/onboarding", json=PLAN, headers=headers)
    await client.post("/v1/onboarding", json=PLAN, headers=headers)

    assert await db.scalar(
        select(func.count())
        .select_from(UserPreference)
        .where(UserPreference.user_id == funded_account.user_id)
    ) == 1


async def test_one_account_never_answers_for_another(
    client, db, funded_account, bearer, ledger
):
    """The user is taken from the credential, never from the body."""
    stranger = await create_funded_account(db, ledger)

    await client.post("/v1/onboarding", json=PLAN, headers=bearer(stranger.user_id))

    assert await db.scalar(
        select(func.count())
        .select_from(Situation)
        .where(Situation.user_id == funded_account.user_id)
    ) == 0


async def test_describing_a_room_without_a_credential_records_nothing(client, db):
    response = await client.post("/v1/onboarding", json=PLAN)

    assert response.status_code == 401
    assert await db.scalar(select(func.count()).select_from(Situation)) == 0
