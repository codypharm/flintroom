"""Behavior of the minutes ledger.

Written against docs/minutes-ledger-and-sessions.md. Flintroom sells minutes of
live interrogation; these tests are the enforcement of the Metering Rules, not a
restatement of them.
"""

import uuid

from app.modules.billing.schemas import Bucket, EntryReason


async def test_charging_a_tick_decrements_allowance_and_records_an_entry(ledger, account):
    """The tracer bullet: time served comes off the balance and leaves a trail.

    Both halves matter. The cached balance is what the session-start path reads,
    and the entry is the audit trail CLAUDE.md requires for every decrement.
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=300,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-allowance-period-1",
    )

    balance = await ledger.charge_tick(
        user_id=account.user_id,
        session_id=uuid.uuid4(),
        tick_index=0,
        seconds=15,
    )

    assert balance.allowance_seconds == 285
    assert balance.total_seconds == 285

    entries = await ledger.entries(user_id=account.user_id)
    ticks = [e for e in entries if e.reason is EntryReason.TICK]
    assert len(ticks) == 1
    assert ticks[0].delta_seconds == -15
    assert ticks[0].bucket is Bucket.ALLOWANCE


async def test_a_tick_spends_allowance_then_free_then_topup(ledger, account):
    """Spend what expires soonest, then what was free, then what was paid for.

    A user must never burn purchased top-up minutes while granted ones remain —
    Product.md §4.5. One tick can straddle buckets, and each bucket it touches
    gets its own entry so the trail says which minutes were actually spent.
    """
    for bucket, reason in (
        (Bucket.TOPUP, EntryReason.GRANT_TOPUP),
        (Bucket.FREE, EntryReason.GRANT_FREE),
        (Bucket.ALLOWANCE, EntryReason.GRANT_ALLOWANCE),
    ):
        await ledger.grant(
            user_id=account.user_id,
            bucket=bucket,
            seconds=10,
            reason=reason,
            idempotency_key=f"grant-{bucket.value}",
        )

    balance = await ledger.charge_tick(
        user_id=account.user_id,
        session_id=uuid.uuid4(),
        tick_index=0,
        seconds=25,
    )

    assert (balance.allowance_seconds, balance.free_seconds, balance.topup_seconds) == (0, 0, 5)

    ticks = [e for e in await ledger.entries(user_id=account.user_id) if e.reason is EntryReason.TICK]
    assert [(t.bucket, t.delta_seconds) for t in ticks] == [
        (Bucket.ALLOWANCE, -10),
        (Bucket.FREE, -10),
        (Bucket.TOPUP, -5),
    ]


async def test_replaying_a_tick_does_not_charge_twice(ledger, account):
    """Retries are safe, including when the tick straddled two buckets.

    Ticking in arrears means the client retries whenever a response is lost, so
    a replay must be inert. The tick as a whole is the unit of idempotency: a
    replay recomputed per bucket would find the first bucket already drained,
    slide down to the next one, and charge the user a second time.
    """
    session_id = uuid.uuid4()
    for bucket, reason in (
        (Bucket.ALLOWANCE, EntryReason.GRANT_ALLOWANCE),
        (Bucket.TOPUP, EntryReason.GRANT_TOPUP),
    ):
        await ledger.grant(
            user_id=account.user_id,
            bucket=bucket,
            seconds=10,
            reason=reason,
            idempotency_key=f"grant-{bucket.value}",
        )

    first = await ledger.charge_tick(
        user_id=account.user_id, session_id=session_id, tick_index=0, seconds=15
    )
    replay = await ledger.charge_tick(
        user_id=account.user_id, session_id=session_id, tick_index=0, seconds=15
    )

    assert first.total_seconds == 5
    assert replay.total_seconds == 5

    entries = await ledger.entries(user_id=account.user_id)
    assert sum(1 for e in entries if e.reason is EntryReason.TICK) == 2
