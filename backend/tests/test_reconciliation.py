"""The cached balance must always equal the replayed entry log.

This is the invariant the whole append-only design exists to provide. The
balance on `accounts` is a cache; `ledger_entries` is the truth. Where they
disagree the cache is wrong, and the point of the model is that the
disagreement is *detectable* rather than silent.

Any future operation that moves a balance without writing an entry breaks this
test, which is the intended alarm.
"""

import uuid
from datetime import UTC, datetime

from freezegun import freeze_time

from app.modules.billing.schemas import Bucket, EntryReason

_BUCKET_FIELD = {
    Bucket.ALLOWANCE: "allowance_seconds",
    Bucket.FREE: "free_seconds",
    Bucket.TOPUP: "topup_seconds",
}


async def assert_reconciles(ledger, user_id) -> None:
    balance = await ledger.balance(user_id=user_id)
    entries = await ledger.entries(user_id=user_id)

    for bucket, field in _BUCKET_FIELD.items():
        replayed = sum(e.delta_seconds for e in entries if e.bucket is bucket)
        assert replayed == getattr(balance, field), (
            f"{bucket.value}: entries replay to {replayed}, "
            f"cached balance says {getattr(balance, field)}"
        )


async def test_a_full_account_lifetime_reconciles(ledger, db, account):
    """Grants, a straddling spend, an overdraft, forgiveness, and a period roll.

    Run end to end rather than as separate cases, because reconciliation is a
    property of the whole history — each operation has to leave the log and the
    cache agreeing with every operation that came before it.
    """
    account.entitlement_tier = "starter"
    account.period_id = 1
    account.period_ends_at = datetime(2026, 8, 20, tzinfo=UTC)
    await db.commit()

    with freeze_time("2026-08-11"):
        await ledger.grant(
            user_id=account.user_id,
            bucket=Bucket.FREE,
            seconds=900,
            reason=EntryReason.GRANT_FREE,
            idempotency_key="signup-free-minutes",
        )
        await ledger.grant(
            user_id=account.user_id,
            bucket=Bucket.TOPUP,
            seconds=1200,
            reason=EntryReason.GRANT_TOPUP,
            idempotency_key="topup-quick-1",
        )
        await assert_reconciles(ledger, account.user_id)

        # A session long enough to drain free, then bite into top-up.
        session_id = uuid.uuid4()
        for index, seconds in enumerate((600, 600, 600)):
            await ledger.charge_tick(
                user_id=account.user_id,
                session_id=session_id,
                tick_index=index,
                seconds=seconds,
            )
        await assert_reconciles(ledger, account.user_id)

        # A second session that runs past zero into grace, then settles.
        overdrawn_session = uuid.uuid4()
        await ledger.charge_tick(
            user_id=account.user_id,
            session_id=overdrawn_session,
            tick_index=0,
            seconds=400,
        )
        assert (await ledger.balance(user_id=account.user_id)).total_seconds < 0
        await assert_reconciles(ledger, account.user_id)

        await ledger.forgive_overdraft(
            user_id=account.user_id, session_id=overdrawn_session
        )
        await assert_reconciles(ledger, account.user_id)

    # The period rolls: unspent allowance expires and the new month is granted.
    with freeze_time("2026-09-25"):
        await ledger.ensure_current_period(user_id=account.user_id)
        await assert_reconciles(ledger, account.user_id)
