import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.models import Account, LedgerEntry
from app.modules.billing.schemas import Balance, Bucket, EntryReason, LedgerEntryRead
from app.modules.billing.tiers import MONTHLY_ALLOWANCE_SECONDS

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


class LedgerService:
    """The only path through which the minutes ledger changes.

    Nothing outside this class writes `accounts` balances or `ledger_entries`.
    That is what makes the audit trail complete rather than mostly complete.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

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
                idempotency_key=idempotency_key,
            )
        )

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
            raise LookupError(f"no ledger account for user {user_id}")
        return account

    @staticmethod
    def _balance_of(account: Account) -> Balance:
        return Balance(
            allowance_seconds=account.balance_allowance_seconds,
            free_seconds=account.balance_free_seconds,
            topup_seconds=account.balance_topup_seconds,
        )
