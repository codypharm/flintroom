"""Deleting an account, and proving it happened.

`docs/account-deletion.md` decides what is destroyed, what is anonymised, and
why the two differ. Apple has required in-app deletion since 2022 for any app
supporting account creation, so this is a store blocker rather than a courtesy.

**Here rather than in a module of its own**, because the account is the subject
and `Account` lives in billing. The work is unavoidably cross-cutting — it
destroys sessions and materials while anonymising the ledger — and there is no
module boundary that makes that tidy. What matters is that it is one place, and
that `KNOWN_TABLES` below makes forgetting a table a test failure.

**The failure mode is silence.** `user_id` is a plain UUID and never a foreign
key to `auth.users` (`CLAUDE.md` → Database portability), which is the decision
separating a weekend migration from a quarter-long one. Nothing cascades from a
*user*, so every table is named by hand, and one left out is personal data
retained forever with nothing raising.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DeletionSweepUnconfigured
from app.core.database import rows_touched
from app.core.logging import get_logger
from app.core.storage import ObjectStorage
from app.modules.audit_log.schemas import AuditEventType
from app.modules.audit_log.service import AuditService
from app.modules.auth.models import AuthIdentity, RefreshToken
# The anonymised tables are imported for their side effect: a model that no
# module in the test's import graph has touched is absent from
# `Base.metadata`, and the guard in `test_account_deletion.py` compares
# against exactly that. An unimported table makes the guard pass by not
# looking, which is the one way it can fail silently.
from app.modules.billing.models import Account, LedgerEntry
from app.modules.ingestion.models import ExtractionCost, Material
from app.modules.onboarding.models import Situation
from app.modules.panels.models import CustomArchetype
from app.modules.sessions.models import Session, SessionRecording, UserPreference
from app.modules.voice.costs import SessionCost
from app.modules.voice.recording import recording_key

log = get_logger(__name__, tag="billing")

#: How long "deleted" means "hidden" before it means gone.
#:
#: The architect's choice over immediate deletion, on the ground that it
#: recovers the misclick — which matters on an account with real sessions in it.
#: What it costs is stated in `docs/account-deletion.md` and must not be
#: forgotten: a disclosure sentence, a sweep that can silently stop running, and
#: a week in which the data is alive while the user believes otherwise.
WINDOW = timedelta(days=7)

#: **Destroying this is the anonymisation.** Nothing else has to be rewritten.
#:
#: `auth_identities` is the only row that maps a `user_id` to a person — it
#: carries the provider subject and the email. `accounts` holds tier, period and
#: three balances and nothing else, so once the identity is gone the UUID is an
#: opaque key pointing at a bucket of numbers.
#:
#: The first version of this module reassigned every surviving row to a shared
#: nil UUID. That is impossible — `ledger_entries.user_id` is a foreign key to
#: `accounts.user_id`, which is the primary key, so there is nothing to repoint
#: it at — and it would have been worse if it worked: one shared tombstone makes
#: every departed user's ledger indistinguishable from every other's, so a
#: chargeback or a tax query about a single purchase could never be answered
#: again. Keeping the opaque key keeps that answerable while keeping the person
#: out of it.
IDENTIFYING = AuthIdentity

#: The models the purge deletes by name, in the order it deletes them.
#:
#: Declared here rather than inline in `_purge` so the suite can check that
#: `DESTROYED` below is exactly what this reaches. Before that check existed,
#: naming a table in `DESTROYED` and deleting nothing passed every test — proven
#: by mutation on 2026-08-18, a full day after `user_preferences` shipped that
#: way.
#:
#: `AuthIdentity` is last, and not cosmetically: it is the row whose absence
#: anonymises everything left behind, so it goes once the rest already has
#: rather than leaving a window where the identity is severed from live data.
PURGED = (
    Session,
    Material,
    UserPreference,
    Situation,
    RefreshToken,
    AuthIdentity,
    CustomArchetype,
)

#: Destroyed by their parent rather than by name.
#:
#: Both carry a denormalised `user_id` *and* cascade — `material_claims` from
#: `materials`, `voice_tickets` from `sessions`. They are listed because "it
#: cascades" is a fact about today's schema and this is here for the day
#: somebody changes it. Do not add an explicit delete for either: a redundant
#: one would look like the load-bearing one and would survive the cascade being
#: dropped.
CASCADING = frozenset({"material_claims", "voice_tickets"})

#: Every table whose rows are gone when a purge finishes.
#:
#: Required to equal `PURGED` plus `CASCADING` exactly, so a promise made here
#: and wired to nothing fails at declaration. That is the second of the two
#: mistakes this module can make; the first is forgetting a table entirely, and
#: `KNOWN_TABLES` catches that one.
#:
#: Fixing either failure means deciding destroy-or-anonymise and recording it in
#: `docs/account-deletion.md` — never appending a name to make the red go away.
DESTROYED = frozenset(
    {model.__tablename__ for model in PURGED} | CASCADING
)

#: Kept, and anonymous by consequence rather than by rewriting.
#: `docs/account-deletion.md` decisions 1-3.
#:
#: **`accounts` belongs here, and sat in `DESTROYED` until 2026-08-18.** The
#: purge has always kept its row — it holds tier, period and three balances, and
#: the ledger, the cost telemetry and the audit trail all point at it — so
#: filing it under "destroyed" was a lie about the one set that answers "what
#: did deleting my account destroy". The behaviour never changed; only the
#: category, which the reachability check found the moment it was written.
#:
#: It is the one row here that is *touched*: the purge stamps `deleted_at` on
#: it. That is a tombstone on a surviving row, not a rewrite of what it holds.
ANONYMISED_TABLES = frozenset(
    {
        "accounts",
        "ledger_entries",
        "session_costs",
        "extraction_costs",
        "audit_events",
    }
)

KNOWN_TABLES = DESTROYED | ANONYMISED_TABLES


class AccountDeletion:
    """Requesting, cancelling, and finally performing a deletion."""

    def __init__(
        self,
        db: AsyncSession,
        storage: ObjectStorage | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._db = db
        # Optional because `request` and `cancel` never touch a bucket, and one
        # of them is called from sign-in — which has no business acquiring an
        # object store in order to answer a question about a column. `sweep`
        # refuses without it rather than defaulting to a purge that skips the
        # objects, because that purge destroys the rows pointing at them and
        # nothing can find them afterwards.
        self._storage = storage
        self._audit = audit or AuditService(db)

    async def request(self, *, user_id: uuid.UUID) -> datetime:
        """Mark the account and start the window. Returns when it closes.

        **Set once, never advanced.** A client that retries, or a user who taps
        twice because nothing visibly happened, must not push the purge back
        another seven days each time — that is a deletion which recedes from the
        person who asked for it. The `IS NULL` guard is what makes the second
        call a no-op rather than an extension.

        The date is returned rather than only the fact, and it is the second
        call that makes it worth doing: an unchanged answer to a repeated
        request is how a client can *see* that the window did not move. It is
        also the only thing a user needs in order to use the window — being told
        the deletion is recoverable without being told until when is not a
        recovery path.
        """
        marked = await self._db.execute(
            update(Account)
            .where(
                Account.user_id == user_id,
                Account.deletion_requested_at.is_(None),
            )
            .values(deletion_requested_at=func.now())
        )

        # Signing out is part of asking, not part of the purge. The window is
        # seven days long and a refresh token spans all of it, so a credential
        # somebody else is holding would outlive the moment its owner asked to
        # be forgotten — on an account that is still fully usable, which is the
        # whole point of the window.
        #
        # Written here rather than through `RefreshTokenService` deliberately.
        # Every method there commits, and the sign-out has to land in the same
        # transaction as the mark: two commits leave a state where the tokens
        # are dead and nothing was scheduled, or the reverse.
        #
        # Revoked rather than deleted, matching `sign_out`. A deleted row makes
        # a replay look like a token we never issued instead of one that was
        # revoked, and the difference is what reuse detection reads.
        await self._db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=func.now())
        )

        if rows_touched(marked):
            self._audit.stage(
                AuditEventType.ACCOUNT_DELETION_REQUESTED, user_id=user_id
            )
            log.info("account_deletion_requested", user_id=str(user_id))

        await self._db.commit()

        # Read back rather than returned from the UPDATE, because the second
        # call updates nothing and still owes an answer — and the answer it
        # owes is the *original* date. `func.now()` is the transaction's clock,
        # so this is the value that was actually stored either way.
        requested = await self._db.scalar(
            select(Account.deletion_requested_at).where(Account.user_id == user_id)
        )

        # The column is nullable and by here it cannot be null: this method has
        # either just set it or found it already set. Asserted rather than
        # left implicit, because the alternative failure is `None + WINDOW` —
        # a `TypeError` surfacing as a 500 on the endpoint Apple requires, with
        # a traceback rather than a sentence.
        assert requested is not None
        return requested + WINDOW

    async def cancel(self, *, user_id: uuid.UUID) -> bool:
        """Call it off. Returns whether there was anything to call off.

        A boolean rather than a raise, because every sign-in runs this and
        almost none of them find anything. Raising would make the ordinary path
        an exception handler, and force a caller to tell "nothing to cancel"
        apart from "the database is down" in order to decide whether to let
        somebody in.

        **The caller owes the user a sentence.** An account that quietly
        un-deletes itself is worse than one that stayed deleted, because they
        never learn their data is still there.
        """
        cleared = await self._db.execute(
            update(Account)
            .where(
                Account.user_id == user_id,
                Account.deletion_requested_at.is_not(None),
            )
            .values(deletion_requested_at=None)
        )

        if cleared_rows := rows_touched(cleared):
            self._audit.stage(
                AuditEventType.ACCOUNT_DELETION_CANCELLED, user_id=user_id
            )
            log.info("account_deletion_cancelled", user_id=str(user_id))

        await self._db.commit()
        return bool(cleared_rows)

    async def sweep(self) -> int:
        """Purge every account whose window has closed. Returns how many.

        The count is returned so the loop can log it, and so its *absence* is
        detectable: `docs/deployment.md` already treats sweep silence as an
        alertable condition for recordings, because audio outliving a published
        promise is invisible from inside. This is the same failure with a worse
        subject.
        """
        if self._storage is None:
            # Refused rather than degraded. A purge without the bucket destroys
            # `session_recordings` and `materials`, which are the only rows that
            # know an object exists — so the objects survive with nothing left
            # pointing at them, and no later sweep can ever find them.
            #
            # `docs/deployment.md` already treats a misconfigured store as the
            # dangerous case for recordings. Here it is worse, because the
            # evidence goes with the data.
            raise DeletionSweepUnconfigured()

        due = await self._db.execute(
            select(Account.user_id).where(
                Account.deletion_requested_at.is_not(None),
                Account.deletion_requested_at < func.now() - WINDOW,
                # Already purged accounts keep their request timestamp — it is
                # when somebody asked, which stays true. Without this the sweep
                # would re-purge them every pass, writing an audit row each time
                # and making the count meaningless as an alerting signal.
                Account.deleted_at.is_(None),
            )
        )

        purged = 0
        for (user_id,) in due:
            try:
                await self._purge(user_id)
            except Exception:
                # Broad, per account, and the same call `SweepRunner._guarded`
                # makes one level up — for the same reason and with a narrower
                # blast radius. The purge is all-or-nothing by design, so one
                # bucket that will not part with one key would otherwise stop
                # every other deletion in the system indefinitely, and the
                # symptom would be a loop that looks quietly healthy.
                #
                # Nothing marks the account as handled, so it is met again next
                # pass. The rollback matters: the audit row was staged before
                # the failure and must not ride out on the next account's
                # commit, attributing a deletion that did not happen.
                await self._db.rollback()
                log.exception("account_purge_failed", user_id=str(user_id))
                continue
            purged += 1

        # Unconditionally, including the empty pass. `docs/deployment.md` makes
        # a sweep's *silence* the alert signal, because nothing raises when a
        # loop stops running — and of the sweeps here this is the one whose
        # silence means people who asked to be forgotten were not.
        log.info("account_deletions_swept", purged=purged)
        return purged

    async def _purge(self, user_id: uuid.UUID) -> None:
        """Everything, in one transaction.

        Objects, then rows, then the account's tombstone — and that order is
        load-bearing. The account row is the last thing touched and the only one
        that survives; stamping it first would leave a window in which a crash
        had marked an account deleted while its sessions were still readable.

        **The account is not destroyed**, despite once being filed that way.
        `ledger_entries`, `session_costs` and `audit_events` all point at it, so
        it keeps its `user_id` as an opaque key and gains a `deleted_at`. See
        `ANONYMISED_TABLES`, which is where it belongs and now sits.

        The audit row is staged before any of it, for the same reason a
        settlement stages before it commits: the proof and the act land together
        or neither does.
        """
        self._audit.stage(AuditEventType.ACCOUNT_DELETED, user_id=user_id)

        # Objects first, and this is the same ordering `RecordingRetention`
        # argues for, with the stakes raised. There the row survives the audio
        # and carries a `deleted_at`, so a row-first crash is at least
        # *visible*. Here the rows are destroyed, so a row-first crash leaves an
        # object nothing points at and no sweep can reach.
        #
        # A store that raises therefore aborts the whole purge: the transaction
        # rolls back, the account keeps its mark, and the next pass tries again.
        await self._erase(user_id)

        # Content, and the identity that makes any of it a person's. Nine tables
        # cascade from `sessions` and `material_claims` from `materials`, so
        # naming the parents is enough — see `CASCADING`. The order within
        # `PURGED` is deliberate and documented there.
        for table in PURGED:
            await self._db.execute(delete(table).where(table.user_id == user_id))

        # The account row stays. Its `user_id` is now an opaque key, and the
        # ledger, the cost telemetry and the audit trail keep pointing at it.
        await self._db.execute(
            update(Account)
            .where(Account.user_id == user_id)
            .values(deleted_at=func.now())
        )

        await self._db.commit()
        log.info("account_deleted", user_id=str(user_id))

    async def _erase(self, user_id: uuid.UUID) -> None:
        """Every object this account owns, out of the bucket.

        Nothing cascades into object storage. Postgres takes
        `session_recordings` and `materials` with their parents and the bytes
        stay exactly where they were, so this is the only thing standing
        between a deletion and audio that outlives the account it belonged to.

        Deleted unconditionally, including a source document extraction already
        purged and a recording the retention sweep already expired. S3 does not
        treat a missing key as an error, so the alternative is a filtered query
        that has to stay correct as those two lifecycles change — for no saving
        beyond a round trip on an account being destroyed anyway.

        The thumbnail is named separately because it is a separate key, chosen
        that way in `ingestion/models.py` so retention could be expressed as a
        bucket rule over a prefix. It is also the object most easily forgotten:
        a title slide routinely carries the company name and the round size,
        and the model's own docstring says so.
        """
        assert self._storage is not None  # `sweep` refuses without it.

        rooms = await self._db.execute(
            select(SessionRecording.session_id)
            .join(Session, Session.id == SessionRecording.session_id)
            .where(Session.user_id == user_id)
        )
        keys = [recording_key(session_id) for (session_id,) in rooms]

        decks = await self._db.execute(
            select(Material.storage_key, Material.thumbnail_key).where(
                Material.user_id == user_id
            )
        )
        for storage_key, thumbnail_key in decks:
            keys.append(storage_key)
            if thumbnail_key:
                keys.append(thumbnail_key)

        for key in keys:
            await self._storage.delete(key)

        # The count, never the keys. A material key carries the user and the
        # material id, and a room key carries the session — identifiers a
        # deleted account should stop appearing under, in a line whose whole
        # purpose is to prove it stopped.
        log.info("account_objects_erased", user_id=str(user_id), objects=len(keys))
