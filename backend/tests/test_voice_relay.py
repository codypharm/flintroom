"""The voice relay — where a provider's stream drives the session state machine.

The relay is the first production caller of `activate`, `fail`, `record_speech`
and `record_progress`. Those seams were cut when the state machine was built
(`docs/minutes-ledger-and-sessions.md` Part 2) and have had no caller since, so
until now nothing in the running system could move a session out of
`provisioning`.

Faked here: the vendor and the client socket, which are the two system
boundaries. Everything else is real — the database, the ledger, the session
service — because a relay tested against a fake session service would prove only
that the fake agrees with itself.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, update

from app.core.errors import ProviderUnavailable
from app.modules.billing.tiers import FREE_TIER_LIFETIME_SECONDS
from app.modules.sessions.models import Session as SessionModel
from app.modules.sessions.models import SessionPhaseSpan
from app.modules.sessions.reaper import ORPHAN_TIMEOUT
from app.modules.sessions.schemas import IDLE_LIMIT, EndReason, SessionState
from app.modules.voice.events import ChannelReady, Heartbeat, UserSpoke
from app.modules.voice.relay import VoiceRelay
from tests.fakes import (
    DyingVoiceProvider,
    FakeVoiceProvider,
    UnavailableVoiceProvider,
)


async def _running_for(db, session, *, seconds: int) -> None:
    """Make the open interrogation span look `seconds` old.

    The same technique the meter tests use, and for the same reason: elapsed
    time is Postgres' arithmetic on the span, so freezing Python's clock would
    move nothing that the meter actually reads.
    """
    await db.execute(
        update(SessionPhaseSpan)
        .where(
            SessionPhaseSpan.session_id == session.id,
            SessionPhaseSpan.ended_at.is_(None),
        )
        .values(started_at=func.now() - timedelta(seconds=seconds))
    )
    await db.commit()


async def _last_heard_from(db, session, *, seconds: int) -> None:
    """Backdate the progress clock, leaving the span alone.

    Separate from `_running_for` because the two clocks answer different
    questions — how long the room has run, and how long since the channel last
    delivered anything — and a helper that moved both would make either test
    pass for the other's reason.
    """
    await db.execute(
        update(SessionModel)
        .where(SessionModel.id == session.id)
        .values(last_progress_at=func.now() - timedelta(seconds=seconds))
    )
    await db.commit()


async def test_a_channel_that_reports_ready_activates_the_session(
    db, sessions, funded_account
):
    """The room opens when the provider says the channel is up — not before.

    `start` deliberately bills nothing: a session sits in `provisioning` while
    agent spin-up runs, because spin-up takes real time and can fail before any
    audio exists. Activation is the moment the meter becomes entitled to charge,
    so it belongs to the provider reporting readiness and to nothing else.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    assert session.state is SessionState.PROVISIONING

    relay = VoiceRelay(db, provider=FakeVoiceProvider([ChannelReady()]))
    await relay.run(session_id=session.id)

    assert (await sessions.get(session_id=session.id)).state is SessionState.ACTIVE


async def test_a_provider_that_never_comes_up_fails_the_session_and_bills_nothing(
    db, sessions, ledger, funded_account
):
    """Spin-up died before any audio existed, so there is nothing to settle.

    This is the case `provisioning` and `failed` were added for: without them a
    spin-up failure is indistinguishable from a real session in every query and
    every cost report. `settled_at` stays null, which is what keeps a room that
    never opened out of the cost reports entirely.

    The balance is asserted rather than assumed. A user whose room failed to
    open and who was charged for it would be the single worst bug this module
    could ship.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    before = await ledger.balance(user_id=funded_account.user_id)

    relay = VoiceRelay(db, provider=UnavailableVoiceProvider())
    with pytest.raises(ProviderUnavailable):
        await relay.run(session_id=session.id)

    failed = await sessions.get(session_id=session.id)
    assert failed.state is SessionState.FAILED
    assert failed.end_reason is EndReason.PROVISIONING_FAILED
    assert failed.settled_at is None

    after = await ledger.balance(user_id=funded_account.user_id)
    assert after.total_seconds == before.total_seconds


async def test_a_provider_that_dies_mid_room_settles_it_and_refunds_the_minutes(
    db, sessions, ledger, meter, funded_account
):
    """The room broke after it had opened, so there is money to give back.

    A different ending from the one above, and deliberately not reachable by the
    same path: this session reached `active`, which the state machine will not
    let move to `failed`. It has to settle, and settling is what triggers the
    refund `REFUND_REASONS` already maps for a provider failure.

    The whole session comes back, not part of it. Settlement treats a provider
    failure as undelivered from tick zero — unlike an idle timeout, where the
    room worked right up until the user stopped answering.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await VoiceRelay(db, provider=FakeVoiceProvider([ChannelReady()])).run(
        session_id=session.id
    )

    # A minute of interrogation, actually billed, so the refund has something
    # to reverse rather than trivially passing against a zero charge.
    await _running_for(db, session, seconds=60)
    await meter.sweep()
    charged = await ledger.balance(user_id=funded_account.user_id)
    assert charged.total_seconds < FREE_TIER_LIFETIME_SECONDS

    # No ChannelReady this time: the room is already open, and the stream simply
    # stops. Re-announcing readiness would be the provider re-activating a live
    # session, which the state machine refuses outright.
    relay = VoiceRelay(db, provider=DyingVoiceProvider([]))
    with pytest.raises(ProviderUnavailable):
        await relay.run(session_id=session.id)

    closed = await sessions.get(session_id=session.id)
    assert closed.state is SessionState.SETTLED
    assert closed.end_reason is EndReason.PROVIDER_FAILURE

    restored = await ledger.balance(user_id=funded_account.user_id)
    assert restored.total_seconds == FREE_TIER_LIFETIME_SECONDS


async def test_a_user_who_is_speaking_keeps_the_room_from_being_reaped_as_idle(
    db, sessions, meter, funded_account
):
    """The point of the speech seam, asserted as the behaviour it protects.

    Deliberately not written as "`last_user_speech_at` was set" — that is the
    mechanism, and a test naming it would survive the seam being wired to
    nothing useful. What the product promises is that a user who is talking is
    not thrown out of the room, so that is what is asserted.

    Only *user* speech counts. A panel monologuing at an empty room is the
    expensive failure the idle timeout exists to catch, which is why the meter
    measures silence from the user rather than from the channel.
    """
    idle_seconds = int(IDLE_LIMIT.total_seconds()) + 10
    session = await sessions.start(user_id=funded_account.user_id)
    await VoiceRelay(db, provider=FakeVoiceProvider([ChannelReady()])).run(
        session_id=session.id
    )
    await _running_for(db, session, seconds=idle_seconds)

    # Long enough that the very next sweep would close this room, had nobody
    # said anything in it.
    await VoiceRelay(db, provider=FakeVoiceProvider([UserSpoke()])).run(
        session_id=session.id
    )
    await meter.sweep()

    still_running = await sessions.get(session_id=session.id)
    assert still_running.state is SessionState.ACTIVE
    assert still_running.end_reason is None


async def test_a_channel_still_delivering_keeps_the_room_from_being_reaped_as_orphaned(
    db, sessions, reaper, funded_account
):
    """The heartbeat seam, likewise asserted through what it prevents.

    Distinct from the idle clock above and not a duplicate of it: idle asks
    whether the *user* is still participating, this asks whether the *channel*
    is still delivering. A room can fail either check while passing the other —
    a user talking into a dead socket, or a healthy stream nobody is answering
    — and they end the session under different reasons, one refunded and one
    not.

    This is the seam the heartbeat decision rests on. There is no HTTP endpoint
    for it precisely because the backend holds the stream and already knows.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await VoiceRelay(db, provider=FakeVoiceProvider([ChannelReady()])).run(
        session_id=session.id
    )
    await _last_heard_from(db, session, seconds=int(ORPHAN_TIMEOUT.total_seconds()) + 10)

    await VoiceRelay(db, provider=FakeVoiceProvider([Heartbeat()])).run(
        session_id=session.id
    )
    await reaper.reap()

    still_running = await sessions.get(session_id=session.id)
    assert still_running.state is SessionState.ACTIVE
    assert still_running.end_reason is None
