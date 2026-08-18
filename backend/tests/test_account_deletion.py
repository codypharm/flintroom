"""Deleting an account, and proving it happened.

`docs/account-deletion.md` decides what is destroyed, what is anonymised, and
why the two differ. Apple has required in-app deletion since 2022, so this is a
store blocker rather than a courtesy, and `docs/privacy-policy.md` cannot be
published while it claims a control that does not exist.

**The failure mode here is silence.** `user_id` is a plain UUID and never a
foreign key to `auth.users` — the portability decision `CLAUDE.md` calls the
difference between a weekend migration and a quarter-long one. Nothing cascades
from a *user*, so every table is named by hand, and a table left out is personal
data retained forever with nothing raising. The first test below is the guard
that turns that from a promise into a failure.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.core.database import Base
from app.modules.billing.models import Account, LedgerEntry
from app.modules.auth.models import AuthIdentity
from app.modules.billing.deletion import KNOWN_TABLES, AccountDeletion
from app.modules.sessions.models import Session
from app.modules.sessions.schemas import EndReason


def test_every_table_carrying_a_user_is_accounted_for():
    """The guard that makes the plain-UUID decision safe rather than only cheap.

    Adding a table with a `user_id` and forgetting the deletion path is not a
    bug that surfaces — it is data quietly retained after somebody was told it
    was gone, and nothing anywhere raises. So the suite raises instead.

    Asserted against the metadata rather than a hand list, so the check cannot
    drift from the schema: a new table appears here the moment it is declared.
    Fixing a failure means deciding destroy-or-anonymise for the new table and
    saying so in `docs/account-deletion.md`, not appending a name to make the
    red go away.
    """
    carrying = {
        name
        for name, table in Base.metadata.tables.items()
        if "user_id" in table.columns
    }

    assert carrying <= KNOWN_TABLES, (
        f"these carry user_id and no deletion decision: {carrying - KNOWN_TABLES}"
    )


async def test_a_request_hides_the_account_without_destroying_it_yet(
    db, funded_account
):
    """Seven days, and the window is the architect's call over immediacy.

    It recovers the misclick, which matters on an account with real sessions in
    it. What it costs is that "deleted" means "hidden" until the sweep runs —
    so the row must still be there, and must no longer be usable.
    """
    await AccountDeletion(db).request(user_id=funded_account.user_id)

    assert await _account_exists(db, funded_account.user_id)
    assert await _requested_at(db, funded_account.user_id) is not None


async def test_asking_twice_does_not_move_the_date(db, funded_account):
    """Idempotent, and the specific harm is a window that never closes.

    A client that retries — or a user who taps twice because nothing visibly
    happened — must not push the purge back another seven days each time. That
    is a deletion which recedes from the person who asked for it.
    """
    deletion = AccountDeletion(db)

    await deletion.request(user_id=funded_account.user_id)
    first = await _requested_at(db, funded_account.user_id)

    await deletion.request(user_id=funded_account.user_id)
    again = await _requested_at(db, funded_account.user_id)

    assert again == first


async def test_signing_in_calls_it_off(db, funded_account):
    """The architect's choice, and the message is the load-bearing half.

    An account that quietly un-deletes itself is worse than one that stayed
    deleted, because the user never learns their data is still there. The
    service's job is the state change; telling them is the caller's, and the
    audit row is what makes it provable afterwards.
    """
    deletion = AccountDeletion(db)
    await deletion.request(user_id=funded_account.user_id)

    cancelled = await deletion.cancel(user_id=funded_account.user_id)

    assert cancelled is True
    assert await _requested_at(db, funded_account.user_id) is None


async def test_cancelling_an_account_nobody_deleted_is_not_an_error(
    db, funded_account
):
    """Every sign-in runs this check, and almost none of them find anything.

    Raising would make the ordinary path an exception handler, and the caller
    would have to tell "nothing to cancel" apart from "the database is down" to
    decide whether to let somebody in.
    """
    assert await AccountDeletion(db).cancel(user_id=funded_account.user_id) is False


async def test_the_sweep_leaves_nothing_of_the_person_and_all_of_the_money(
    db, engine, sessions, settlement, funded_account, ledger
):
    """The purge, and the two halves of `docs/account-deletion.md`.

    Content goes: the session and everything cascading from it. Money stays,
    anonymised — `ledger_entries` is append-only and is the record RevenueCat's
    purchases are accounted against, so destroying it would leave the
    reconciliation test reconciling against gaps.

    Asserted on both at once, because the risk is doing one and calling it done.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await sessions.activate(session_id=session.id)
    await settlement.close(session_id=session.id, end_reason=EndReason.USER_ENDED)

    # The identity is created here on purpose. Without it the assertion below
    # counts zero either way, and this is the single most load-bearing check in
    # the task — destroying `auth_identities` IS the anonymisation, and a
    # mutation that skipped it passed the first version of this test.
    await _signed_in_with(db, funded_account.user_id)

    deletion = AccountDeletion(db)
    await deletion.request(user_id=funded_account.user_id)
    await _requested_days_ago(db, funded_account.user_id, days=8)

    swept = await deletion.sweep()

    assert swept == 1
    # Content: gone, with nine tables cascading behind it.
    assert await db.get(Session, session.id) is None
    # The identity: gone, and its absence is what anonymises the rest.
    assert await _identities(db, funded_account.user_id) == 0
    # The money: untouched, still pointing at an account row that now maps to
    # nobody. Destroying it would leave RevenueCat holding purchases this side
    # cannot account for.
    assert await _ledger_rows(db, funded_account.user_id) > 0
    assert await _deleted_at(db, funded_account.user_id) is not None


async def test_a_purged_account_is_not_purged_again(
    db, funded_account
):
    """The sweep runs continuously, and every pass sees every purged account.

    `deletion_requested_at` is deliberately not cleared by the purge — it is
    when somebody asked, and that stays true. So without `deleted_at` guarding
    the selection, an emptied account matches the sweep's criteria forever:
    another audit row every pass, and a swept count that never falls to zero.

    That count is the alerting signal `docs/deployment.md` wants, and a signal
    that is permanently non-zero is a signal nobody can read.
    """
    deletion = AccountDeletion(db)
    await deletion.request(user_id=funded_account.user_id)
    await _requested_days_ago(db, funded_account.user_id, days=8)

    assert await deletion.sweep() == 1
    assert await deletion.sweep() == 0


async def test_the_sweep_does_not_touch_an_account_inside_its_window(
    db, funded_account
):
    """Seven days means seven days.

    The sweep runs continuously and every pass sees accounts mid-window. One
    that purged early would destroy data the product had promised was still
    recoverable — and would do it to whichever account happened to be nearest
    the boundary.
    """
    deletion = AccountDeletion(db)
    await deletion.request(user_id=funded_account.user_id)
    await _requested_days_ago(db, funded_account.user_id, days=6)

    assert await deletion.sweep() == 0
    assert await _deleted_at(db, funded_account.user_id) is None


async def _requested_days_ago(db, user_id, *, days: int) -> None:
    """Backdate the request rather than sleeping through the window."""
    await db.execute(
        update(Account)
        .where(Account.user_id == user_id)
        .values(deletion_requested_at=func.now() - timedelta(days=days))
    )
    await db.commit()


async def _signed_in_with(db, user_id) -> None:
    """The row that makes a UUID a person — a Google sign-in, with an email."""
    db.add(
        AuthIdentity(
            provider="google",
            subject="1179428813",
            user_id=user_id,
            email="someone@example.com",
            email_verified=True,
        )
    )
    await db.commit()


async def _column(db, user_id, column):
    """One column, read past the identity map.

    Core selects rather than `db.get`, and not fussiness: the service commits,
    which expires every ORM object in the session, and touching an expired
    attribute afterwards triggers a lazy refresh — blocking IO inside an async
    call, surfacing as `MissingGreenlet` rather than as anything resembling the
    real cause. `sessions/service.py` documents the same hazard for the same
    reason.
    """
    rows = await db.execute(select(column).where(Account.user_id == user_id))
    return rows.scalar_one_or_none()


async def _requested_at(db, user_id):
    return await _column(db, user_id, Account.deletion_requested_at)


async def _deleted_at(db, user_id):
    return await _column(db, user_id, Account.deleted_at)


async def _account_exists(db, user_id) -> bool:
    return await _column(db, user_id, Account.user_id) is not None


async def _identities(db, user_id) -> int:
    rows = await db.execute(
        select(func.count())
        .select_from(AuthIdentity)
        .where(AuthIdentity.user_id == user_id)
    )
    return rows.scalar_one()


async def _ledger_rows(db, user_id) -> int:
    rows = await db.execute(
        select(func.count())
        .select_from(LedgerEntry)
        .where(LedgerEntry.user_id == user_id)
    )
    return rows.scalar_one()
