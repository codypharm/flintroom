"""Provenance on money movements, and the event log beside them.

`ledger_entries` is already the complete record of *what* moved. What a support
escalation actually asks is *who caused it* and *what else was happening*, and
neither is answerable from a delta and a reason code alone.

Money is recorded once, in the ledger. `audit_events` carries what does not move
money — denied starts, entitlement changes, rejected webhooks — so there is
never a second copy of a balance change to drift out of agreement with the first.
"""

import uuid

from app.core.actors import Actor, ActorContext
from app.modules.audit_log.schemas import AuditEventType
from app.modules.billing.schemas import Bucket, EntryReason
from app.modules.billing.service import LedgerService


async def test_a_money_movement_records_who_caused_it(db, account):
    """A RevenueCat grant and a support credit must be tellable apart.

    Both are positive top-up entries with identical shape. Without an actor the
    ledger cannot answer "did we give this person minutes, or did they buy
    them", which is the first question in any billing dispute.
    """
    webhook = LedgerService(
        db,
        actor=ActorContext(
            actor=Actor.WEBHOOK,
            actor_id="revenuecat:evt_9f2a",
            request_id="req-abc",
        ),
    )

    await webhook.grant(
        user_id=account.user_id,
        bucket=Bucket.TOPUP,
        seconds=1200,
        reason=EntryReason.GRANT_TOPUP,
        idempotency_key="topup-1",
    )

    entry = (await webhook.entries(user_id=account.user_id))[-1]
    assert entry.actor is Actor.WEBHOOK
    assert entry.actor_id == "revenuecat:evt_9f2a"
    assert entry.request_id == "req-abc"


async def test_ticks_are_attributed_to_the_system_by_default(ledger, account):
    """The tick loop is not a person, and must not look like one."""
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=300,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )
    await ledger.charge_tick(
        user_id=account.user_id, session_id=uuid.uuid4(), tick_index=0, seconds=15
    )

    entry = (await ledger.entries(user_id=account.user_id))[-1]
    assert entry.actor is Actor.SYSTEM
    assert entry.actor_id is None


async def test_a_denied_action_is_recorded_even_though_no_money_moved(audit, account):
    """A refusal is the event most worth having and the easiest to lose.

    Nothing moves in the ledger when a start is denied, so without this the
    record simply has a gap where the interesting thing happened. CLAUDE.md
    requires denials logged with the user and the attempted action.
    """
    await audit.record(
        AuditEventType.SESSION_START_DENIED,
        user_id=account.user_id,
        reason="no_minutes_remaining",
        requested_panel_size=3,
    )

    events = await audit.events_for_user(user_id=account.user_id)
    assert len(events) == 1
    assert events[0].event_type is AuditEventType.SESSION_START_DENIED
    assert events[0].context == {
        "reason": "no_minutes_remaining",
        "requested_panel_size": 3,
    }


async def test_audit_context_is_redacted_like_a_log_line(audit, account):
    """The database is not a safe place for a secret either.

    Redaction that only applies to stdout means the first person to add an audit
    call with a webhook signature in context has written it to disk permanently
    — and audit rows are append-only, so it cannot be edited out.
    """
    await audit.record(
        AuditEventType.WEBHOOK_REJECTED,
        provider="revenuecat",
        x_signature="deadbeef",
    )

    events = await audit.events_for_user(user_id=None)
    assert events[0].context == {"provider": "revenuecat", "x_signature": "[redacted]"}


async def test_the_account_timeline_interleaves_money_and_events(admin, ledger, audit, account):
    """An operator reads one story, not two tables joined by eye.

    A billing dispute is usually "they were denied, then they bought a top-up,
    then the session still failed" — that sequence only exists when the ledger
    and the event log are merged in time order.
    """
    await audit.record(
        AuditEventType.SESSION_START_DENIED,
        user_id=account.user_id,
        reason="no_minutes_remaining",
    )
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.TOPUP,
        seconds=1200,
        reason=EntryReason.GRANT_TOPUP,
        idempotency_key="topup-1",
    )
    await audit.record(
        AuditEventType.SESSION_STARTED,
        user_id=account.user_id,
        session_id=uuid.uuid4(),
    )

    timeline = await admin.account_timeline(user_id=account.user_id)

    # Most recent first: an operator reads backwards from the incident.
    assert [item.kind for item in timeline] == ["event", "money", "event"]
    assert [item.summary for item in timeline] == [
        "session_started",
        "grant_topup",
        "session_start_denied",
    ]

    money = timeline[1]
    assert money.delta_seconds == 1200
    assert money.balance_after_seconds == 1200
    assert money.actor is Actor.SYSTEM
