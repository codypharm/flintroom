import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.errors import AccountNotFound
from app.core.logging import get_logger
from app.modules.billing.models import Account, LedgerEntry
from app.modules.billing.schemas import Balance, Bucket, EntryReason, LedgerEntryRead
from app.modules.billing.tiers import (
    FREE_TIER_LIFETIME_SECONDS,
    MONTHLY_ALLOWANCE_SECONDS,
)

_BUCKET_BALANCE_COLUMN = {
    Bucket.ALLOWANCE: "balance_allowance_seconds",
    Bucket.FREE: "balance_free_seconds",
    Bucket.TOPUP: "balance_topup_seconds",
}

#: Allowance expires at the period boundary, so spend it before anything else.
#: Top-up is last because the user paid for it and it never expires.
SPEND_ORDER = (Bucket.ALLOWANCE, Bucket.FREE, Bucket.TOPUP)

#: Placeholder cadence. The real boundary comes from the RevenueCat entitlement
#: period, not the calendar — a user who subscribed on the 3rd renews on the 3rd.
#: Replace this when the RevenueCat webhook lands; see docs/minutes-ledger-and-sessions.md.
PERIOD_LENGTH = timedelta(days=30)

log = get_logger(__name__, tag="billing")


class LedgerService:
    """The only path through which the minutes ledger changes.

    Nothing outside this class writes `accounts` balances or `ledger_entries`.
    That is what makes the audit trail complete rather than mostly complete.
    """

    def __init__(self, db: AsyncSession, actor: ActorContext | None = None) -> None:
        self._db = db
        # Defaults to system: the overwhelmingly common writer is the tick loop
        # and the lazy period reset. Request-scoped callers pass their own.
        self._actor = actor or ActorContext.system()

    async def grant(
        self,
        *,
        user_id: uuid.UUID,
        bucket: Bucket,
        seconds: int,
        reason: EntryReason,
        idempotency_key: str,
    ) -> Balance:
        """Add seconds to a bucket."""
        account = await self._load_account(user_id, for_update=True)
        self._stage(
            account=account,
            bucket=bucket,
            delta_seconds=seconds,
            reason=reason,
            idempotency_key=idempotency_key,
        )
        await self._db.commit()
        return self._balance_of(account)

    async def grant_signup_free_minutes(self, *, user_id: uuid.UUID) -> None:
        """The free tier's lifetime minutes, granted once per user ever.

        Product.md §4.4: 15 minutes, one complete session, never renewed. Into
        the free bucket rather than the allowance one, which is what stops
        `ensure_current_period` from expiring them at a period boundary and what
        makes "lifetime" true in code rather than only in the pricing page.

        Idempotent by construction — the key is derived from the user, and
        `idempotency_key` is globally unique, so a second grant cannot insert.
        That makes it safe to attempt on *every* sign-in, which is deliberate:
        a process that died between creating an account and granting its
        minutes would otherwise leave a user permanently unable to start a
        session, with no way to notice and no way to repair it. Attempting each
        time turns that into something that fixes itself the next time they open
        the app.
        """
        key = f"grant_free:{user_id}"
        if await self._entry_exists(idempotency_key=key):
            return

        try:
            await self.grant(
                user_id=user_id,
                bucket=Bucket.FREE,
                seconds=FREE_TIER_LIFETIME_SECONDS,
                reason=EntryReason.GRANT_FREE,
                idempotency_key=key,
            )
        except IntegrityError:
            # Two devices signing in for the first time at the same moment. The
            # check above cannot see a sibling transaction's uncommitted row, so
            # the unique index is what actually arbitrates — as it does for
            # every other duplicate in this ledger.
            await self._db.rollback()
            log.info("free_grant_already_made", user_id=str(user_id))
            return

        log.info(
            "free_grant_made",
            user_id=str(user_id),
            seconds=FREE_TIER_LIFETIME_SECONDS,
        )

    async def _entry_exists(self, *, idempotency_key: str) -> bool:
        result = await self._db.execute(
            select(LedgerEntry.id).where(
                LedgerEntry.idempotency_key == idempotency_key
            )
        )
        return result.first() is not None

    async def charge_tick(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        tick_index: int,
        seconds: int,
    ) -> Balance:
        """Charge one interval of interrogation time, in arrears.

        Called after the interval has elapsed, so a crash or dropped network can
        never bill for time the user did not get.

        A single tick can straddle buckets. Each bucket it draws from gets its
        own entry, so the trail records which minutes were actually spent rather
        than only how many.
        """
        # Lock first, then check: a replay that checked before locking could be
        # waved through while the original tick is still uncommitted.
        account = await self._load_account(user_id, for_update=True)

        if await self._tick_already_charged(session_id=session_id, tick_index=tick_index):
            return self._balance_of(account)

        remaining = seconds
        for bucket in SPEND_ORDER:
            if remaining <= 0:
                break
            available = max(getattr(account, _BUCKET_BALANCE_COLUMN[bucket]), 0)
            drawn = min(available, remaining)
            if drawn == 0:
                continue
            self._stage(
                account=account,
                bucket=bucket,
                delta_seconds=-drawn,
                reason=EntryReason.TICK,
                idempotency_key=f"tick:{session_id}:{tick_index}:{bucket.value}",
                session_id=session_id,
                tick_index=tick_index,
            )
            remaining -= drawn

        if remaining > 0:
            # Every bucket is dry and the session is still running, because
            # Product.md §4.5 forbids cutting a live interrogation off. The
            # overdraft lands on allowance: that is the bucket the next period
            # replaces outright, so a forgiven overdraft cannot follow the user
            # around for months.
            self._stage(
                account=account,
                bucket=Bucket.ALLOWANCE,
                delta_seconds=-remaining,
                reason=EntryReason.TICK,
                idempotency_key=f"tick:{session_id}:{tick_index}:overdraft",
                session_id=session_id,
                tick_index=tick_index,
            )

        # One commit for the whole tick. A tick that straddles buckets must land
        # entirely or not at all, or a crash mid-tick bills for a fraction of an
        # interval and leaves the trail disagreeing with the cached balance.
        await self._db.commit()
        log.info(
            "tick_charged",
            user_id=str(user_id),
            session_id=str(session_id),
            tick_index=tick_index,
            seconds=seconds,
            remaining_seconds=account.balance_allowance_seconds
            + account.balance_free_seconds
            + account.balance_topup_seconds,
        )
        return self._balance_of(account)

    async def refund_session(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        reason: EntryReason,
        from_index: int = 0,
    ) -> Balance:
        """Return seconds charged for a session, to the buckets they came from.

        `from_index` refunds only from that tick onward, which is what an idle
        window is: the room worked until the user stopped answering, so the
        earlier intervals were served and are not owed back. Defaults to the
        whole session, because every other refund reason means none of it
        landed.

        Bucket-faithful, not merely amount-faithful. Allowance is replaced
        outright at the next period boundary while top-up minutes never expire
        (§4.5), so refunding top-up time into allowance would hand back the
        right number of seconds and then quietly expire them — a refund for our
        own outage turned into a slower way of taking the user's money.

        Reconstructed from the entries rather than from a running total, because
        the entries are the record; a total can drift, and this is the one place
        that would silently pay out the drift.
        """
        # Lock first, then check — the ordering `charge_tick` uses, and for the
        # same reason: a replay that checked before locking could be waved
        # through while the original refund is still uncommitted.
        account = await self._load_account(user_id, for_update=True)

        if await self._session_already_refunded(session_id=session_id, reason=reason):
            return self._balance_of(account)

        charged = await self._db.execute(
            select(LedgerEntry.bucket, func.sum(LedgerEntry.delta_seconds))
            .where(
                LedgerEntry.session_id == session_id,
                LedgerEntry.reason == EntryReason.TICK.value,
                LedgerEntry.tick_index >= from_index,
            )
            .group_by(LedgerEntry.bucket)
        )

        refunded = 0
        for bucket, total in charged.all():
            # Ticks are negative; the refund is what puts them back.
            seconds = -int(total)
            if seconds <= 0:
                continue
            self._stage(
                account=account,
                bucket=Bucket(bucket),
                delta_seconds=seconds,
                reason=reason,
                # One key per bucket per session, so a retried settlement
                # reaches the same balance instead of paying out again.
                idempotency_key=f"refund:{session_id}:{reason.value}:{bucket}",
                session_id=session_id,
            )
            refunded += seconds

        await self._db.commit()
        log.info(
            "session_refunded",
            user_id=str(user_id),
            session_id=str(session_id),
            reason=reason.value,
            refunded_seconds=refunded,
        )
        return self._balance_of(account)

    async def forgive_overdraft(self, *, user_id: uuid.UUID, session_id: uuid.UUID) -> Balance:
        """Write off a grace overdraft at settlement.

        A session that reaches zero mid-interrogation keeps running on a bounded
        overdraft, because Product.md §4.5 forbids cutting the panel off. At
        settlement the overdraft is forgiven rather than carried into next month:
        chasing two minutes is the engaged-user farming §4.5 warns against.

        The write-off is a typed entry, not a reset of the balance, so replaying
        the log still reproduces the cache.
        """
        account = await self._load_account(user_id, for_update=True)

        overdraft = -account.balance_allowance_seconds
        if overdraft <= 0:
            return self._balance_of(account)

        self._stage(
            account=account,
            bucket=Bucket.ALLOWANCE,
            delta_seconds=overdraft,
            reason=EntryReason.GRACE_FORGIVEN,
            idempotency_key=f"grace_forgiven:{session_id}",
            session_id=session_id,
        )
        await self._db.commit()
        log.info(
            "grace_overdraft_forgiven",
            user_id=str(user_id),
            session_id=str(session_id),
            forgiven_seconds=overdraft,
        )
        return self._balance_of(account)

    async def ensure_current_period(self, *, user_id: uuid.UUID) -> Balance:
        """Roll the account onto the current period if its boundary has passed.

        Lazy rather than scheduled: the stack has no scheduler, and a lazy reset
        has no silent failure mode. A dropped RevenueCat webhook costs nothing
        because the next read repairs it.
        """
        account = await self._load_account(user_id, for_update=True)
        now = datetime.now(UTC)

        if account.period_ends_at is None or account.period_ends_at > now:
            return self._balance_of(account)

        # Walk to the *current* period. Granting per elapsed boundary would hand
        # a user who was away for a quarter three allowances at once.
        elapsed = 0
        while account.period_ends_at <= now:
            account.period_ends_at = account.period_ends_at + PERIOD_LENGTH
            elapsed += 1
        account.period_id += elapsed

        # No roll-over (Product.md §4.4). The remainder is written off as its own
        # entry rather than overwritten, so replaying the log still reproduces
        # the cached balance.
        #
        # Only a positive remainder expires. A negative one is a grace overdraft,
        # and clearing it here would forgive it under the wrong reason code —
        # forgiveness is a `grace_forgiven` entry written at settlement.
        remainder = account.balance_allowance_seconds
        if remainder > 0:
            self._stage(
                account=account,
                bucket=Bucket.ALLOWANCE,
                delta_seconds=-remainder,
                reason=EntryReason.EXPIRE_ALLOWANCE,
                idempotency_key=f"expire_allowance:{user_id}:{account.period_id}",
            )

        allowance = MONTHLY_ALLOWANCE_SECONDS.get(account.entitlement_tier)
        if allowance is not None:
            self._stage(
                account=account,
                bucket=Bucket.ALLOWANCE,
                delta_seconds=allowance,
                reason=EntryReason.GRANT_ALLOWANCE,
                idempotency_key=f"grant_allowance:{user_id}:{account.period_id}",
            )

        await self._db.commit()
        log.info(
            "period_reset",
            user_id=str(user_id),
            period_id=account.period_id,
            periods_elapsed=elapsed,
            expired_seconds=remainder if remainder > 0 else 0,
            granted_seconds=allowance or 0,
        )
        return self._balance_of(account)

    async def balance(self, *, user_id: uuid.UUID) -> Balance:
        return self._balance_of(await self._load_account(user_id))

    async def entries(self, *, user_id: uuid.UUID) -> list[LedgerEntryRead]:
        """The audit trail, oldest first."""
        result = await self._db.execute(
            select(LedgerEntry).where(LedgerEntry.user_id == user_id).order_by(LedgerEntry.id)
        )
        return [LedgerEntryRead.model_validate(row) for row in result.scalars()]

    def _stage(
        self,
        *,
        account: Account,
        bucket: Bucket,
        delta_seconds: int,
        reason: EntryReason,
        idempotency_key: str,
        session_id: uuid.UUID | None = None,
        tick_index: int | None = None,
    ) -> None:
        """Queue one entry and its balance movement. The caller commits."""
        column = _BUCKET_BALANCE_COLUMN[bucket]
        setattr(account, column, getattr(account, column) + delta_seconds)

        self._db.add(
            LedgerEntry(
                user_id=account.user_id,
                session_id=session_id,
                tick_index=tick_index,
                bucket=bucket.value,
                delta_seconds=delta_seconds,
                reason=reason.value,
                actor=self._actor.actor.value,
                actor_id=self._actor.actor_id,
                request_id=self._actor.request_id,
                balance_after_seconds=self._balance_of(account).total_seconds,
                idempotency_key=idempotency_key,
            )
        )

    async def ticks_charged(self, *, session_id: uuid.UUID) -> int:
        """How many intervals of this session have already been billed.

        Exists so the meter can skip what it has already charged without
        reaching into `ledger_entries` itself — the ledger stays the only module
        that knows how a tick is recorded. Answers with the count implied by the
        highest index rather than a row count, because a tick that straddled
        buckets wrote more than one entry for a single interval.
        """
        result = await self._db.execute(
            select(func.max(LedgerEntry.tick_index)).where(
                LedgerEntry.session_id == session_id,
                LedgerEntry.tick_index.is_not(None),
            )
        )
        highest = result.scalar_one_or_none()
        return 0 if highest is None else highest + 1

    async def _session_already_refunded(
        self, *, session_id: uuid.UUID, reason: EntryReason
    ) -> bool:
        """Has this session already been refunded under this reason?

        Without this a retried settlement hits the unique index on
        `idempotency_key` and raises — which is safe for the balance but leaves
        the session stuck in `finalizing` forever, since the retry can never
        complete. That is the one failure state no user action resolves.
        """
        result = await self._db.execute(
            select(LedgerEntry.id)
            .where(
                LedgerEntry.session_id == session_id,
                LedgerEntry.reason == reason.value,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _tick_already_charged(self, *, session_id: uuid.UUID, tick_index: int) -> bool:
        """Has this tick been charged before?

        The sequential replay is caught here. The concurrent one — two retries
        arriving at once — is caught by the unique index on `idempotency_key`,
        which is why that constraint stays even though this check exists.
        """
        result = await self._db.execute(
            select(LedgerEntry.id)
            .where(
                LedgerEntry.session_id == session_id,
                LedgerEntry.tick_index == tick_index,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _load_account(self, user_id: uuid.UUID, *, for_update: bool = False) -> Account:
        """Load an account, optionally locking it for the rest of the transaction.

        Every write path locks. Balances are read-modify-write — a tick has to
        see the true per-bucket amounts to decide how to split itself — so two
        unlocked writers on one account each compute an absolute new value and
        the last commit erases the others. A webhook grant landing during a live
        session is exactly that collision.

        The lock is per account row, and Product.md allows a user only one
        active session at a time, so genuine contention here is close to zero:
        this serializes one user against themselves, never one user against
        another.

        `populate_existing` forces the locked read to refresh the object rather
        than answer from the session's identity map, which would reinstate the
        stale value the lock was taken to avoid.
        """
        statement = (
            select(Account)
            .where(Account.user_id == user_id)
            # Always refresh. A balance is money, and answering it from a
            # session's identity map reports what that session last saw rather
            # than what is committed.
            .execution_options(populate_existing=True)
        )
        if for_update:
            statement = statement.with_for_update()

        account = (await self._db.execute(statement)).scalar_one_or_none()
        if account is None:
            raise AccountNotFound(user_id=str(user_id))
        return account

    @staticmethod
    def _balance_of(account: Account) -> Balance:
        return Balance(
            allowance_seconds=account.balance_allowance_seconds,
            free_seconds=account.balance_free_seconds,
            topup_seconds=account.balance_topup_seconds,
        )
