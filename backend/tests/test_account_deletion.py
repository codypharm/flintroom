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

import importlib
import pkgutil

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import func, select, update

from app.core.database import Base
from app.core.errors import DeletionSweepUnconfigured, NotAuthenticated
from app.modules.billing.models import Account, LedgerEntry
from app.modules.auth.models import AuthIdentity
from app.modules.auth.refresh import RefreshTokenService
from app.modules.billing.deletion import (
    CASCADING,
    DESTROYED,
    KNOWN_TABLES,
    PURGED,
    AccountDeletion,
)
from app.modules.ingestion.models import Material
from app.modules.onboarding.models import Situation
from app.modules.onboarding.schemas import Answers
from app.modules.onboarding.service import OnboardingService
from app.modules.sessions.models import Session, SessionRecording, UserPreference
from app.modules.sessions.schemas import EndReason
from app.modules.voice.recording import recording_key
from tests.materials import uploaded
from tests.pdfs import minimal_pdf


def _import_every_model_module() -> None:
    """Declaring a table is not registering one.

    `Base.metadata` is populated as a side effect of import, so a module nothing
    has imported contributes nothing — and the first thing anybody does with a
    new table is declare it before wiring it up. Walking the packages makes the
    guard independent of whether some other test happened to import the right
    thing.

    A missing `models` is ordinary — not every module has one. A
    `ModuleNotFoundError` naming anything *else* is a genuine broken import
    inside a models file, and is re-raised rather than swallowed as absence.
    """
    import app.modules as modules

    for found in pkgutil.iter_modules(modules.__path__):
        target = f"app.modules.{found.name}.models"
        try:
            importlib.import_module(target)
        except ModuleNotFoundError as missing:
            if missing.name != target:
                raise


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

    **The sentence above was a promise the code did not keep**, found on
    2026-08-20 while adding `custom_archetypes`: the new table declared its
    `user_id`, joined no deletion path, and this test passed. `Base.metadata`
    holds what has been *imported*, not what exists, and a fresh `models.py`
    that nothing imports yet is invisible to it — which is precisely the silent
    retention this guard exists to prevent, arriving through the guard itself.
    Every models module is imported first now.
    """
    _import_every_model_module()

    carrying = {
        name
        for name, table in Base.metadata.tables.items()
        if "user_id" in table.columns
    }

    assert carrying <= KNOWN_TABLES, (
        f"these carry user_id and no deletion decision: {carrying - KNOWN_TABLES}"
    )


def test_every_table_we_promise_to_destroy_is_actually_reached():
    """The second mistake, which the guard above cannot see.

    Deciding a table's fate and *carrying it out* are separate acts, and until
    this existed only the first was checked. Adding a name to `DESTROYED` turned
    the guard green whether or not anything ever deleted a row — proven by
    mutation on 2026-08-18: removing `user_preferences` from the purge left all
    thirteen tests passing, a full day after it shipped.

    So `DESTROYED` is now required to be exactly what the purge reaches, by
    deletion or by cascade. A table named here and wired to nothing fails at
    declaration, the same way an undeclared one already did.

    The first thing this caught was `accounts`, which sat in `DESTROYED` while
    the purge deliberately keeps its row — see `ANONYMISED_TABLES`, where it now
    is. The behaviour was right the whole time; the category was a lie, and a
    lie in the set that answers "what did deleting my account destroy" is worth
    a failing test.
    """
    reached = {model.__tablename__ for model in PURGED} | CASCADING

    assert DESTROYED == reached, (
        f"promised but unreached: {DESTROYED - reached}; "
        f"reached but unpromised: {reached - DESTROYED}"
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
    db, engine, storage, sessions, settlement, funded_account, ledger
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

    # Seeded for exactly the same reason, and after the same mutation survived:
    # naming a table in `DESTROYED` is what the guard above checks, and deleting
    # it is not. The two are separate mistakes and only rows catch the second.
    await OnboardingService(db).record(
        user_id=funded_account.user_id,
        answers=Answers(situation="board_review", role="exec", audience=["budget"]),
    )

    deletion = AccountDeletion(db, storage)
    await deletion.request(user_id=funded_account.user_id)
    await _requested_days_ago(db, funded_account.user_id, days=8)

    swept = await deletion.sweep()

    assert swept == 1
    # Content: gone, with nine tables cascading behind it.
    assert await db.get(Session, session.id) is None
    # The identity: gone, and its absence is what anonymises the rest.
    assert await _identities(db, funded_account.user_id) == 0
    # The meeting they were preparing for, and the answers that shaped the room.
    # Their own content, with no accounting obligation holding it back.
    assert await _situations(db, funded_account.user_id) == 0
    assert await db.get(UserPreference, funded_account.user_id) is None
    # The money: untouched, still pointing at an account row that now maps to
    # nobody. Destroying it would leave RevenueCat holding purchases this side
    # cannot account for.
    assert await _ledger_rows(db, funded_account.user_id) > 0
    assert await _deleted_at(db, funded_account.user_id) is not None


async def test_a_purged_account_is_not_purged_again(db, storage, funded_account):
    """The sweep runs continuously, and every pass sees every purged account.

    `deletion_requested_at` is deliberately not cleared by the purge — it is
    when somebody asked, and that stays true. So without `deleted_at` guarding
    the selection, an emptied account matches the sweep's criteria forever:
    another audit row every pass, and a swept count that never falls to zero.

    That count is the alerting signal `docs/deployment.md` wants, and a signal
    that is permanently non-zero is a signal nobody can read.
    """
    deletion = AccountDeletion(db, storage)
    await deletion.request(user_id=funded_account.user_id)
    await _requested_days_ago(db, funded_account.user_id, days=8)

    assert await deletion.sweep() == 1
    assert await deletion.sweep() == 0


async def test_the_sweep_does_not_touch_an_account_inside_its_window(
    db, storage, funded_account
):
    """Seven days means seven days.

    The sweep runs continuously and every pass sees accounts mid-window. One
    that purged early would destroy data the product had promised was still
    recoverable — and would do it to whichever account happened to be nearest
    the boundary.
    """
    deletion = AccountDeletion(db, storage)
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


async def _situations(db, user_id) -> int:
    rows = await db.execute(
        select(func.count()).select_from(Situation).where(Situation.user_id == user_id)
    )
    return rows.scalar_one()


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


async def test_requesting_deletion_signs_every_device_out(db, funded_account):
    """`docs/account-deletion.md`: revoked at request time, not at purge.

    The window is seven days long, and a refresh token left alive spans all of
    it. Signing out is part of the request rather than a courtesy that follows
    it: a credential someone else is holding must not outlive the moment its
    owner asked to be forgotten, and the whole point of the window is that the
    account is still there to be used.

    Asserted on the credential failing rather than on a column, because a
    `revoked_at` that nothing reads would pass a column check and still let the
    session continue.
    """
    refresh = RefreshTokenService(db)
    token = await refresh.issue(user_id=funded_account.user_id)

    await AccountDeletion(db).request(user_id=funded_account.user_id)

    with pytest.raises(NotAuthenticated):
        await refresh.rotate(token=token)


async def test_the_purge_takes_the_audio_out_of_storage(
    db, storage, sessions, settlement, funded_account
):
    """`docs/account-deletion.md`: object storage is included.

    Nothing cascades into a bucket. `session_recordings` goes with the session
    it hangs off, and the `.ogg` behind it stays exactly where it was — so a
    purge that only touched Postgres would leave a row saying the audio is gone
    over audio that is not, which the retention design calls out as worse than
    either state on its own.

    Worse here than there, because the row is destroyed rather than marked: the
    orphaned object has nothing left pointing at it, so no later sweep can find
    it and nothing will ever raise.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await sessions.activate(session_id=session.id)
    await settlement.close(session_id=session.id, end_reason=EndReason.USER_ENDED)
    key = await _room_audio(db, storage, session.id)

    deletion = AccountDeletion(db, storage)
    await deletion.request(user_id=funded_account.user_id)
    await _requested_days_ago(db, funded_account.user_id, days=8)

    assert await deletion.sweep() == 1
    assert await storage.exists(key) is False


async def _room_audio(db, storage, session_id) -> str:
    """A room with audio behind it, without paying for the encoder.

    The bytes are not opus and nothing here decodes them. What is under test is
    that the key is reached, and a real object in real MinIO is what proves it —
    a fake store would agree with whatever the deletion path happened to do.
    """
    key = recording_key(session_id)
    await storage.put(key, b"not really opus", content_type="audio/ogg")
    db.add(SessionRecording(session_id=session_id, byte_size=15))
    await db.commit()
    return key


async def test_the_purge_takes_the_deck_and_its_thumbnail_too(
    db, storage, ingestion, funded_account
):
    """Two keys, and the second is the one that gets forgotten.

    `ingestion/models.py` keeps the thumbnail under a key of its own so that
    retention could one day be a bucket rule over a prefix — which means a
    deletion written against `storage_key` alone looks complete and leaves the
    rendered first page behind. That page is not the innocuous artefact it
    sounds like: a title slide routinely carries the company name, the round
    size and the word "Confidential", and the model says so in writing.
    """
    deck, thumbnail = await _uploaded_deck(db, storage, ingestion, funded_account)

    deletion = AccountDeletion(db, storage)
    await deletion.request(user_id=funded_account.user_id)
    await _requested_days_ago(db, funded_account.user_id, days=8)

    assert await deletion.sweep() == 1
    assert await storage.exists(deck) is False
    assert await storage.exists(thumbnail) is False


async def test_a_sweep_without_an_object_store_refuses_rather_than_orphaning(
    db, funded_account
):
    """Deny by default, on the one path where the evidence goes with the data.

    `session_recordings` and `materials` are the only rows that know an object
    exists, and the purge destroys them. A sweep that ran without the store
    would therefore not leave audio behind *visibly*, the way a failed
    retention pass does — it would leave it behind with nothing pointing at it,
    unreachable by any later sweep and undetectable by anything short of
    listing the bucket.
    """
    deletion = AccountDeletion(db)
    await deletion.request(user_id=funded_account.user_id)
    await _requested_days_ago(db, funded_account.user_id, days=8)

    with pytest.raises(DeletionSweepUnconfigured):
        await deletion.sweep()

    assert await _deleted_at(db, funded_account.user_id) is None


async def test_a_store_that_fails_leaves_the_account_for_the_next_pass(
    db, storage, sessions, settlement, funded_account
):
    """One unerasable account must not jam the queue behind it.

    The purge is all-or-nothing on purpose: a store that raises rolls the
    transaction back, so the rows survive alongside the objects rather than
    being destroyed over bytes that are still there. But the sweep runs over
    every due account, and a bucket that is permanently unhappy about one key
    would otherwise stop every other deletion in the system, indefinitely, with
    the failure looking like a quiet loop.

    So the account is skipped, not counted, and met again next pass — the same
    shape ingestion uses for a material whose objects would not go.
    """
    # Both identifiers read out before anything can roll back. A rollback
    # expires every ORM object in the session, and the refresh that follows is
    # blocking IO inside an async call — `MissingGreenlet`, nowhere near the
    # real cause. `_column` below documents the same trap.
    user_id = funded_account.user_id
    session = await sessions.start(user_id=user_id)
    session_id = session.id
    await sessions.activate(session_id=session_id)
    await settlement.close(session_id=session_id, end_reason=EndReason.USER_ENDED)
    await _room_audio(db, storage, session_id)

    await AccountDeletion(db).request(user_id=user_id)
    await _requested_days_ago(db, user_id, days=8)

    assert await AccountDeletion(db, _UnhappyStore(storage)).sweep() == 0
    assert await db.get(Session, session_id) is not None
    assert await _deleted_at(db, user_id) is None

    # And the retry is the point: nothing about the failure marked the account
    # as handled, so the next pass finds it exactly as it was.
    assert await AccountDeletion(db, storage).sweep() == 1


class _UnhappyStore:
    """A store that refuses to delete, and is otherwise real.

    Wrapping rather than faking wholesale: everything the purge does apart from
    the one failing call still goes to MinIO, so the test exercises the real
    query and the real ordering and changes exactly one fact about the world.
    """

    def __init__(self, real) -> None:
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def delete(self, key: str) -> None:
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObject")


async def _uploaded_deck(db, storage, ingestion, account) -> tuple[str, str]:
    """A deck through the real handshake, with both its objects in the bucket.

    `tests/materials.py` rather than a hand-built row, for the reason that file
    gives: a copy drifts, and the copy that drifts is the one that stops
    exercising the real upload and starts asserting against something somebody
    assembled by hand.

    The thumbnail is written directly. Rendering one means running the
    extractor, and what is under test is a key being reached rather than a page
    being drawn.
    """
    material = await uploaded(ingestion, account, minimal_pdf("Gross margin 61%"))

    thumbnail = f"{material.storage_key}.thumb.jpg"
    await storage.put(thumbnail, b"not really a jpeg", content_type="image/jpeg")
    await db.execute(
        update(Material)
        .where(Material.id == material.id)
        .values(thumbnail_key=thumbnail)
    )
    await db.commit()

    return material.storage_key, thumbnail
