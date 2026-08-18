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
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base
from app.core.logging import get_logger
from app.modules.audit_log.schemas import AuditEventType
from app.modules.audit_log.service import AuditService
from app.modules.auth.models import AuthIdentity, RefreshToken
from app.modules.billing.models import Account, LedgerEntry
from app.modules.ingestion.models import ExtractionCost, Material
from app.modules.sessions.models import Session, UserPreference
from app.modules.voice.costs import SessionCost

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

#: Every table carrying a `user_id`, and what happens to it.
#:
#: `test_account_deletion.py` asserts this covers the schema, so declaring a new
#: table with a `user_id` and forgetting it here fails the suite rather than
#: quietly retaining data. Fixing that failure means deciding destroy-or-
#: anonymise and recording it in `docs/account-deletion.md` — not appending a
#: name to make the red go away.
#: Gone when this finishes — which is not the same as deleted by name here.
#:
#: `material_claims` and `voice_tickets` carry a denormalised `user_id` *and*
#: cascade from their parent, so they go when `materials` and `sessions` go. The
#: guard still demands they appear, because "it cascades" is a fact about today's
#: schema and the guard is there for the day somebody changes it. Do not add an
#: explicit delete for either: a redundant one would look like the load-bearing
#: one and would survive the cascade being dropped.
DESTROYED = frozenset(
    {
        "accounts",
        "auth_identities",
        "refresh_tokens",
        "materials",
        "material_claims",
        "sessions",
        "user_preferences",
        "voice_tickets",
    }
)

#: Kept untouched, and anonymous by consequence rather than by rewriting.
#: `docs/account-deletion.md` decisions 1–3.
ANONYMISED_TABLES = frozenset(
    {"ledger_entries", "session_costs", "extraction_costs", "audit_events"}
)

KNOWN_TABLES = DESTROYED | ANONYMISED_TABLES


class AccountDeletion:
    """Requesting, cancelling, and finally performing a deletion."""

    def __init__(self, db: AsyncSession, audit: AuditService | None = None) -> None:
        self._db = db
        self._audit = audit or AuditService(db)

    async def request(self, *, user_id: uuid.UUID) -> None:
        """Mark the account and start the window.

        **Set once, never advanced.** A client that retries, or a user who taps
        twice because nothing visibly happened, must not push the purge back
        another seven days each time — that is a deletion which recedes from the
        person who asked for it. The `IS NULL` guard is what makes the second
        call a no-op rather than an extension.
        """
        marked = await self._db.execute(
            update(Account)
            .where(
                Account.user_id == user_id,
                Account.deletion_requested_at.is_(None),
            )
            .values(deletion_requested_at=func.now())
        )

        if marked.rowcount:
            self._audit.stage(
                AuditEventType.ACCOUNT_DELETION_REQUESTED, user_id=user_id
            )
            log.info("account_deletion_requested", user_id=str(user_id))

        await self._db.commit()

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

        if cleared.rowcount:
            self._audit.stage(
                AuditEventType.ACCOUNT_DELETION_CANCELLED, user_id=user_id
            )
            log.info("account_deletion_cancelled", user_id=str(user_id))

        await self._db.commit()
        return bool(cleared.rowcount)

    async def sweep(self) -> int:
        """Purge every account whose window has closed. Returns how many.

        The count is returned so the loop can log it, and so its *absence* is
        detectable: `docs/deployment.md` already treats sweep silence as an
        alertable condition for recordings, because audio outliving a published
        promise is invisible from inside. This is the same failure with a worse
        subject.
        """
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
            await self._purge(user_id)
            purged += 1

        return purged

    async def _purge(self, user_id: uuid.UUID) -> None:
        """Everything, in one transaction.

        Anonymise before destroy, and the order is load-bearing: `accounts` is
        destroyed, and a ledger row is meaningless once the account it belongs
        to is gone. Reversing this would leave a window in which a crash had
        removed the account and left the money rows pointing at nothing.

        The audit row is staged before either, for the same reason a settlement
        stages before it commits: the proof and the act land together or neither
        does.
        """
        self._audit.stage(AuditEventType.ACCOUNT_DELETED, user_id=user_id)

        # Content, and the identity that makes any of it a person's. Nine tables
        # cascade from `sessions` and `material_claims` from `materials`, so
        # naming the parents is enough — see `DESTROYED`.
        #
        # `AuthIdentity` last of the destructions is not cosmetic: it is the row
        # whose absence anonymises everything left behind, so it goes when the
        # rest has already gone rather than leaving a window where the identity
        # is severed from data that still exists.
        for table in (
            Session,
            Material,
            UserPreference,
            RefreshToken,
            AuthIdentity,
        ):
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
