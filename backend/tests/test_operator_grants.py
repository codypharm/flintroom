"""Minutes a person gives by hand: a promo list, a tester, a complaint made good.

Separate from a purchase in every way the ledger can tell. The reason is its own,
so §4.5's Credit-Toward-Upgrade Rule never reads a gift as a second top-up. The
actor is ADMIN and names the operator, so "why does this user hold ninety
minutes" has an answer with a person in it.
"""

import uuid

import pytest

from app.core.actors import Actor, ActorContext
from app.modules.auth.models import AuthIdentity
from app.modules.billing.grants import GrantInputInvalid, OperatorGrants
from app.modules.billing.models import Account
from app.modules.billing.schemas import Bucket, EntryReason
from app.modules.billing.service import LedgerService
from app.modules.sessions.models import Session
from app.modules.sessions.schemas import EndReason, SessionState
from app.core.database import db_now
from tests.test_reconciliation import assert_reconciles


async def _person(db, email: str, *, verified: bool = True) -> Account:
    account = Account(user_id=uuid.uuid4(), entitlement_tier="free")
    db.add(account)
    await db.flush()
    db.add(
        AuthIdentity(
            user_id=account.user_id,
            provider="google",
            subject=str(uuid.uuid4()),
            email=email,
            email_verified=verified,
        )
    )
    await db.commit()
    return account


# --- The ledger method ------------------------------------------------------


async def test_an_admin_grant_lands_in_topup_and_names_the_operator(db, account):
    """Top-up, because it is the bucket a period boundary never writes off."""
    ledger = LedgerService(db, actor=ActorContext.admin("nonso"))

    granted = await ledger.grant_admin(
        user_id=account.user_id, seconds=3600, idempotency_key="k1"
    )

    assert granted is True
    balance = await ledger.balance(user_id=account.user_id)
    assert balance.topup_seconds == 3600

    [entry] = await ledger.entries(user_id=account.user_id)
    assert entry.reason is EntryReason.GRANT_ADMIN
    assert entry.bucket is Bucket.TOPUP
    assert entry.actor is Actor.ADMIN
    assert entry.actor_id == "nonso"
    await assert_reconciles(ledger, account.user_id)


async def test_the_same_key_grants_once(db, account):
    ledger = LedgerService(db, actor=ActorContext.admin("nonso"))

    assert await ledger.grant_admin(user_id=account.user_id, seconds=600, idempotency_key="k")
    assert not await ledger.grant_admin(user_id=account.user_id, seconds=600, idempotency_key="k")

    assert (await ledger.balance(user_id=account.user_id)).topup_seconds == 600


async def test_only_an_admin_actor_may_grant_by_hand(db, account):
    """A gift attributed to `system` is the unexplained balance the actor exists to prevent."""
    with pytest.raises(PermissionError):
        await LedgerService(db).grant_admin(
            user_id=account.user_id, seconds=600, idempotency_key="k"
        )

    assert (await LedgerService(db).balance(user_id=account.user_id)).topup_seconds == 0


async def test_a_gift_is_not_a_purchase_to_the_upgrade_rule(db, account):
    """Otherwise a promo recipient's first real top-up is steered as their second."""
    account.entitlement_tier = "starter"
    await db.commit()
    ledger = LedgerService(db, actor=ActorContext.admin("nonso"))
    await ledger.grant_admin(user_id=account.user_id, seconds=600, idempotency_key="k")

    options = await ledger.purchase_options(user_id=account.user_id)

    assert options.upgrade_first is False


# --- The batch --------------------------------------------------------------


async def test_a_list_grants_everyone_it_can_find_and_reports_the_rest(db):
    ada = await _person(db, "ada@example.com")
    ben = await _person(db, "ben@example.com")

    report = await OperatorGrants(db, operator="nonso").run(
        emails=["ada@example.com", "ben@example.com", "nobody@example.com"],
        minutes=30,
        campaign="launch-week",
    )

    assert set(report.granted) == {"ada@example.com", "ben@example.com"}
    assert report.not_found == ["nobody@example.com"]
    for person in (ada, ben):
        balance = await LedgerService(db).balance(user_id=person.user_id)
        assert balance.topup_seconds == 30 * 60


async def test_rerunning_a_campaign_skips_who_already_has_it(db):
    """A run that died halfway is re-run, not reasoned about."""
    await _person(db, "ada@example.com")
    grants = OperatorGrants(db, operator="nonso")
    await grants.run(emails=["ada@example.com"], minutes=30, campaign="launch-week")

    await _person(db, "ben@example.com")
    report = await grants.run(
        emails=["ada@example.com", "ben@example.com"], minutes=30, campaign="launch-week"
    )

    assert report.granted == ["ben@example.com"]
    assert report.already_granted == ["ada@example.com"]


async def test_a_new_campaign_grants_the_same_person_again(db):
    ada = await _person(db, "ada@example.com")
    grants = OperatorGrants(db, operator="nonso")

    await grants.run(emails=["ada@example.com"], minutes=10, campaign="launch-week")
    await grants.run(emails=["ada@example.com"], minutes=10, campaign="demo-video")

    assert (await LedgerService(db).balance(user_id=ada.user_id)).topup_seconds == 20 * 60


async def test_a_dry_run_writes_nothing(db):
    ada = await _person(db, "ada@example.com")

    report = await OperatorGrants(db, operator="nonso").run(
        emails=["ada@example.com"], minutes=30, campaign="launch-week", dry_run=True
    )

    assert report.granted == ["ada@example.com"]
    assert await LedgerService(db).entries(user_id=ada.user_id) == []


async def test_an_unverified_address_is_not_a_match(db):
    """The same rule sign-in linking follows: an unverified email is a claim, not a fact."""
    await _person(db, "ada@example.com", verified=False)

    report = await OperatorGrants(db, operator="nonso").run(
        emails=["ada@example.com"], minutes=30, campaign="launch-week"
    )

    assert report.not_found == ["ada@example.com"]


async def test_an_address_on_two_accounts_is_reported_rather_than_guessed(db):
    await _person(db, "ada@example.com")
    await _person(db, "ada@example.com")

    report = await OperatorGrants(db, operator="nonso").run(
        emails=["ada@example.com"], minutes=30, campaign="launch-week"
    )

    assert report.ambiguous == ["ada@example.com"]
    assert report.granted == []


async def test_the_accounts_behind_an_ambiguous_address_are_described_enough_to_choose(db):
    """Granting both pays one person twice; picking one is a guess. So the operator picks."""
    used = await _person(db, "ada@example.com")
    idle = await _person(db, "ada@example.com")
    db.add(
        Session(
            user_id=used.user_id,
            state=SessionState.SETTLED,
            settled_at=await db_now(db),
            end_reason=EndReason.USER_ENDED,
        )
    )
    await db.commit()

    report = await OperatorGrants(db, operator="nonso").run(
        emails=["ada@example.com"], minutes=30, campaign="launch-week"
    )

    candidates = {c.user_id: c for c in report.candidates["ada@example.com"]}
    assert set(candidates) == {used.user_id, idle.user_id}
    assert candidates[used.user_id].providers == ["google"]
    assert candidates[used.user_id].rooms == 1
    assert candidates[used.user_id].last_room_at is not None
    assert candidates[idle.user_id].rooms == 0
    assert candidates[idle.user_id].last_room_at is None
    assert candidates[idle.user_id].joined_at is not None


async def test_an_account_can_be_named_directly(db):
    ada = await _person(db, "ada@example.com")

    report = await OperatorGrants(db, operator="nonso").run(
        user_ids=[ada.user_id], minutes=30, campaign="launch-week"
    )

    assert report.granted == [str(ada.user_id)]
    assert (await LedgerService(db).balance(user_id=ada.user_id)).topup_seconds == 30 * 60


async def test_naming_an_account_and_its_address_in_one_campaign_grants_once(db):
    """The key is the account, however the operator reached it."""
    ada = await _person(db, "ada@example.com")
    grants = OperatorGrants(db, operator="nonso")

    await grants.run(user_ids=[ada.user_id], minutes=30, campaign="launch-week")
    report = await grants.run(emails=["ada@example.com"], minutes=30, campaign="launch-week")

    assert report.already_granted == ["ada@example.com"]
    assert (await LedgerService(db).balance(user_id=ada.user_id)).topup_seconds == 30 * 60


async def test_an_account_that_does_not_exist_is_reported(db):
    missing = uuid.uuid4()

    report = await OperatorGrants(db, operator="nonso").run(
        user_ids=[missing], minutes=30, campaign="launch-week"
    )

    assert report.not_found == [str(missing)]


async def test_one_person_with_two_sign_in_methods_is_one_account(db):
    """Apple and Google with the same address link to one user_id; that is not ambiguity."""
    ada = await _person(db, "ada@example.com")
    db.add(
        AuthIdentity(
            user_id=ada.user_id,
            provider="apple",
            subject=str(uuid.uuid4()),
            email="ada@example.com",
            email_verified=True,
        )
    )
    await db.commit()

    report = await OperatorGrants(db, operator="nonso").run(
        emails=["ada@example.com"], minutes=30, campaign="launch-week"
    )

    assert report.granted == ["ada@example.com"]


async def test_a_pasted_list_is_normalised_and_deduplicated(db):
    ada = await _person(db, "ada@example.com")

    report = await OperatorGrants(db, operator="nonso").run(
        emails=["  Ada@Example.com ", "ada@example.com", ""],
        minutes=30,
        campaign="launch-week",
    )

    assert report.granted == ["ada@example.com"]
    assert (await LedgerService(db).balance(user_id=ada.user_id)).topup_seconds == 30 * 60


@pytest.mark.parametrize(
    ("minutes", "campaign"),
    [
        (0, "launch-week"),
        (-5, "launch-week"),
        (10_000, "launch-week"),
        (30, ""),
        (30, "Launch Week"),
        (30, "x" * 65),
    ],
)
async def test_input_is_refused_before_anything_is_written(db, minutes, campaign):
    """A typo in a promo run is paid for by every address on the list."""
    await _person(db, "ada@example.com")

    with pytest.raises(GrantInputInvalid):
        await OperatorGrants(db, operator="nonso").run(
            emails=["ada@example.com"], minutes=minutes, campaign=campaign
        )


async def test_an_operator_must_be_named(db):
    with pytest.raises(GrantInputInvalid):
        OperatorGrants(db, operator="  ")
