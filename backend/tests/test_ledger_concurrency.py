"""The ledger under concurrent writers.

These are correctness tests, not load tests. Every case here fails with two
concurrent writers; none of them need a thousand. Money must be correct at two
before it is worth asking whether it is fast at a million.
"""

import asyncio
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.billing.schemas import Bucket, EntryReason
from app.modules.billing.service import LedgerService


async def test_concurrent_writers_do_not_overwrite_each_other(engine, account):
    """Simultaneous writers on one account must all survive.

    Read-modify-write in Python is a lost update waiting to happen: every writer
    reads the same balance, each computes an absolute new value, and the last
    commit silently erases the rest. It is not hypothetical — a renewal or
    top-up webhook lands on the same row as the tick loop while the user is
    mid-interrogation.

    Twenty writers rather than two, because with two the bug reproduces only
    when SQLAlchemy happens not to re-read. Correctness here must not depend on
    a caching accident.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def grant_once(index: int) -> None:
        async with factory() as session:
            await LedgerService(session).grant(
                user_id=account.user_id,
                bucket=Bucket.ALLOWANCE,
                seconds=10,
                reason=EntryReason.GRANT_ALLOWANCE,
                idempotency_key=f"grant-{index}",
            )

    await asyncio.gather(*(grant_once(i) for i in range(20)))

    # Read from a fresh session: an already-open one would answer from its own
    # identity map and report what it last saw rather than what is stored.
    async with factory() as session:
        balance = await LedgerService(session).balance(user_id=account.user_id)
    assert balance.allowance_seconds == 200


async def test_concurrent_replays_of_one_tick_charge_once(engine, ledger, account):
    """Two retries in flight at once must not become a 500 or a double charge.

    The existence check cannot see an uncommitted sibling transaction, so both
    replays pass it and race to insert. CLAUDE.md is explicit that a duplicate
    action is never a 500.
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=300,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-period-1",
    )
    session_id = uuid.uuid4()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session_a, factory() as session_b:
        results = await asyncio.gather(
            LedgerService(session_a).charge_tick(
                user_id=account.user_id, session_id=session_id, tick_index=0, seconds=15
            ),
            LedgerService(session_b).charge_tick(
                user_id=account.user_id, session_id=session_id, tick_index=0, seconds=15
            ),
        )

    assert all(r.allowance_seconds == 285 for r in results)
    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == 285

    entries = await ledger.entries(user_id=account.user_id)
    assert sum(1 for e in entries if e.reason is EntryReason.TICK) == 1
