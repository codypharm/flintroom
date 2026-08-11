"""Settlement — where the session state machine and the ledger meet.

`finalizing → settled` is the transition that writes money: refunds for time
the user did not get, and forgiveness of any grace overdraft. It is the one
sequence that must be safely retryable, because the reaper does retry it.
"""

import pytest

from app.core.errors import InvalidStateTransition
from app.modules.billing.schemas import Bucket, EntryReason
from app.modules.sessions.schemas import EndReason, SessionState
from app.modules.sessions.service import SessionService


async def test_settling_forgives_a_grace_overdraft_and_closes_the_session(
    settlement, sessions, ledger, account
):
    """The tracer: state and money move together, or not at all.

    A session that hits zero mid-interrogation keeps running on a bounded
    overdraft, because §4.5 forbids cutting the panel off. Settlement is where
    that debt is written off — leaving it on the account would carry a chased
    two minutes into next month, which is the engaged-user farming §4.5 warns
    against.
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=10,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await ledger.charge_tick(
        user_id=account.user_id, session_id=session.id, tick_index=0, seconds=30
    )
    await sessions.begin_finalizing(
        session_id=session.id, end_reason=EndReason.USER_ENDED
    )

    settled = await settlement.settle(session_id=session.id)

    assert settled.state is SessionState.SETTLED
    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == 0


async def test_a_provider_failure_refunds_to_the_buckets_the_time_came_from(
    settlement, sessions, ledger, account
):
    """Refunding the right *amount* is not enough — the bucket matters.

    Allowance is replaced outright at the next period boundary; top-up minutes
    never expire (§4.5). Refunding top-up time into allowance would return the
    correct number of seconds and then quietly expire them at the next reset,
    turning a refund for our own outage into a slower way of taking the user's
    money. A tick straddling buckets is the normal case, not an exotic one.
    """
    for bucket, seconds in ((Bucket.ALLOWANCE, 20), (Bucket.TOPUP, 60)):
        await ledger.grant(
            user_id=account.user_id,
            bucket=bucket,
            seconds=seconds,
            reason=EntryReason.GRANT_ALLOWANCE
            if bucket is Bucket.ALLOWANCE
            else EntryReason.GRANT_TOPUP,
            idempotency_key=f"grant-{bucket.value}",
        )
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    # 30s of interrogation: 20 from allowance, then 10 from top-up.
    await ledger.charge_tick(
        user_id=account.user_id, session_id=session.id, tick_index=0, seconds=30
    )
    await sessions.begin_finalizing(
        session_id=session.id, end_reason=EndReason.PROVIDER_FAILURE
    )

    await settlement.settle(session_id=session.id)

    balance = await ledger.balance(user_id=account.user_id)
    assert (balance.allowance_seconds, balance.topup_seconds) == (20, 60)

    refunds = [
        entry
        for entry in await ledger.entries(user_id=account.user_id)
        if entry.reason is EntryReason.REFUND_PROVIDER_FAILURE
    ]
    assert sorted((e.bucket.value, e.delta_seconds) for e in refunds) == [
        ("allowance", 20),
        ("topup", 10),
    ]


async def test_settling_twice_refunds_once(
    settlement, sessions, ledger, account, monkeypatch
):
    """The reaper retries settlement, so paying out twice is reachable.

    `finalizing → finalizing` is legal precisely so a settlement that died
    partway can be run again, which means every write here meets a second
    attempt as a matter of course rather than as an anomaly. A second refund
    would credit the account with minutes nobody bought, and — because the
    entries are what reconciliation replays — the drift would look like a
    correct balance.
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=100,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await ledger.charge_tick(
        user_id=account.user_id, session_id=session.id, tick_index=0, seconds=30
    )
    await sessions.begin_finalizing(
        session_id=session.id, end_reason=EndReason.PROVIDER_FAILURE
    )
    # The process dies after the money is written and before the state moves —
    # the one window `finalizing` exists to make recoverable. Note the session
    # cannot be *re*-finalized after settling, because `settled` is terminal by
    # construction; the only reachable retry is this one.
    def die(*args, **kwargs):
        raise RuntimeError("settled before the state moved")

    monkeypatch.setattr(SessionService, "settle", die)
    with pytest.raises(RuntimeError):
        await settlement.settle(session_id=session.id)
    monkeypatch.undo()

    # The reaper cannot tell this session from one that never started settling.
    settled = await settlement.settle(session_id=session.id)

    assert settled.state is SessionState.SETTLED
    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == 100


async def test_settling_a_running_session_writes_no_money(
    settlement, sessions, ledger, account
):
    """The precondition is checked before the ledger, not after.

    `settle` refuses anything but `finalizing`, but that refusal lives in the
    state machine at the *end* of the sequence, so the money is written first
    and the close is rejected afterwards — leaving a committed write against a
    room that is still running.

    Grace forgiveness is where that bites. The overdraft is what the grace cap
    watches, so forgiving it mid-session resets the very number that ends an
    unfunded session: the room keeps ticking, keeps overdrawing, and each
    attempt to settle it wipes the debt again. A session that cannot be settled
    is exactly the one that should not have its balance touched.
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=10,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    # §4.5 forbids cutting the panel off, so this runs 20s past zero.
    await ledger.charge_tick(
        user_id=account.user_id, session_id=session.id, tick_index=0, seconds=30
    )

    with pytest.raises(InvalidStateTransition):
        await settlement.settle(session_id=session.id)

    assert (await ledger.balance(user_id=account.user_id)).allowance_seconds == -20
    assert not [
        entry
        for entry in await ledger.entries(user_id=account.user_id)
        if entry.reason is EntryReason.GRACE_FORGIVEN
    ]
