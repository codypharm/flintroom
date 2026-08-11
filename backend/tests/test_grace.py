"""Grace overdraft and its forgiveness.

Product.md §4.5 forbids interrupting a live interrogation, so a session whose
balance hits zero keeps running on a bounded grace overdraft. The write-off is
recorded as a typed entry rather than by zeroing the balance — replaying the log
has to reproduce the cached balance, which is the whole reason the ledger is
append-only.
"""

import uuid

from app.modules.billing.schemas import Bucket, EntryReason


async def test_forgiving_an_overdraft_clears_it_and_records_why(ledger, account):
    """The write-off is an entry, and it is typed as forgiveness.

    Silently resetting the balance to zero would leave the entry history and the
    cached balance permanently disagreeing, which is exactly the drift the
    append-only model exists to make impossible.
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=10,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )
    session_id = uuid.uuid4()

    # The panel is mid-question; §4.5 says it finishes. This runs 20s past zero.
    overdrawn = await ledger.charge_tick(
        user_id=account.user_id, session_id=session_id, tick_index=0, seconds=30
    )
    assert overdrawn.allowance_seconds == -20

    balance = await ledger.forgive_overdraft(user_id=account.user_id, session_id=session_id)

    assert balance.allowance_seconds == 0

    entries = await ledger.entries(user_id=account.user_id)
    forgiven = [e for e in entries if e.reason is EntryReason.GRACE_FORGIVEN]
    assert [(e.bucket, e.delta_seconds) for e in forgiven] == [(Bucket.ALLOWANCE, 20)]


async def test_forgiving_twice_does_not_hand_out_minutes(ledger, account):
    """Settlement is retried, so forgiveness must be idempotent.

    `finalizing` exists precisely so a crashed settle can be retried, and the
    reaper does retry it. A second forgiveness would credit the overdraft again
    and leave the account with free minutes it never bought.
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=10,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )
    session_id = uuid.uuid4()
    await ledger.charge_tick(
        user_id=account.user_id, session_id=session_id, tick_index=0, seconds=30
    )

    await ledger.forgive_overdraft(user_id=account.user_id, session_id=session_id)
    balance = await ledger.forgive_overdraft(user_id=account.user_id, session_id=session_id)

    assert balance.allowance_seconds == 0
    forgiven = [
        e for e in await ledger.entries(user_id=account.user_id)
        if e.reason is EntryReason.GRACE_FORGIVEN
    ]
    assert len(forgiven) == 1
