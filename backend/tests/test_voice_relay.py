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

import array
import logging
from datetime import timedelta

import pytest
from sqlalchemy import func, update

from app.core.errors import ProviderUnavailable
from app.modules.billing.tiers import FREE_TIER_LIFETIME_SECONDS
from app.modules.sessions.models import Session as SessionModel
from app.modules.sessions.models import SessionPhaseSpan
from app.modules.sessions.reaper import ORPHAN_TIMEOUT
from app.modules.sessions.schemas import (
    IDLE_LIMIT,
    SESSION_LIMIT,
    EndReason,
    SessionState,
)
from app.modules.voice.recording import RoomRecordings, recording_key
from app.modules.voice.events import (
    AgentAudio,
    AgentFinished,
    AgentTranscript,
    ChannelReady,
    Heartbeat,
    Interrupted,
    UserSpoke,
)
from app.modules.voice.relay import VoiceRelay

from .conftest import mark_heard
from tests.fakes import (
    DyingVoiceProvider,
    FakeClientChannel,
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

    relay = VoiceRelay(db, provider=FakeVoiceProvider([ChannelReady()]), client=FakeClientChannel())
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

    relay = VoiceRelay(db, provider=UnavailableVoiceProvider(), client=FakeClientChannel())
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
    await VoiceRelay(db, provider=FakeVoiceProvider([ChannelReady()]), client=FakeClientChannel()).run(
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
    relay = VoiceRelay(db, provider=DyingVoiceProvider([]), client=FakeClientChannel())
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
    await VoiceRelay(db, provider=FakeVoiceProvider([ChannelReady()]), client=FakeClientChannel()).run(
        session_id=session.id
    )
    await _running_for(db, session, seconds=idle_seconds)

    # Long enough that the very next sweep would close this room, had nobody
    # said anything in it.
    await VoiceRelay(db, provider=FakeVoiceProvider([UserSpoke()]), client=FakeClientChannel()).run(
        session_id=session.id
    )
    await meter.sweep()

    still_running = await sessions.get(session_id=session.id)
    assert still_running.state is SessionState.ACTIVE
    assert still_running.end_reason is None


async def test_a_room_the_meter_already_ended_stops_carrying_on_the_next_heartbeat(
    db, sessions, settlement, funded_account
):
    """The phone is finally told when the database ends a room.

    Observed on the first Play build (2026-08-26): the reaper ended three idle
    rooms dead on schedule, and every one of them kept living on the phone —
    timer counting, room apparently open — because the meter and the reaper end
    rooms in the database only, and nothing closed the socket. The architect
    ended one by hand and attributed the close to their own tap.

    The heartbeat is the relay's chance to notice. On a session that is no
    longer active, the relay winds down instead of carrying further events —
    the socket closes, and the shipped app's reconnect flow (docs/reconnect.md)
    turns a dead socket over a settled room into the debrief hand-off.

    The end reason is the part that must not change: the room was ended as
    idle, and a relay that wound down by recording `client_disconnect` over it
    would rewrite why — and with it, what was refunded.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await VoiceRelay(
        db, provider=FakeVoiceProvider([ChannelReady()]), client=FakeClientChannel()
    ).run(session_id=session.id)
    await mark_heard(db, session.id)
    ended = await settlement.close(
        session_id=session.id, end_reason=EndReason.IDLE_TIMEOUT
    )
    assert ended.state is SessionState.SETTLED

    client = FakeClientChannel()
    await VoiceRelay(
        db,
        provider=FakeVoiceProvider(
            [Heartbeat(), AgentTranscript("said after the end", speaker="cfo")]
        ),
        client=client,
    ).run(session_id=session.id)

    # The line after the heartbeat was never carried: the relay stopped at the
    # first beat over a dead room rather than speaking into it.
    assert client.captions == []
    after = await sessions.get(session_id=session.id)
    assert after.state is SessionState.SETTLED
    assert after.end_reason is EndReason.IDLE_TIMEOUT


async def test_what_the_panel_says_reaches_the_phone(db, sessions, funded_account):
    """The relay carries agent audio out to the client, unmodified.

    Byte-identical on purpose. ElevenLabs speaks PCM16 and so does the socket
    to the phone, which is the entire reason the transport decision landed on
    PCM rather than Opus: the relay does no codec work, so there is no decode
    latency in the path Open Risk #3 is about and no C dependency to justify.

    A relay that re-encoded here would be spending part of the ~1.5s budget to
    save uplink bandwidth on a leg that is not the constrained one.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    client = FakeClientChannel()
    frame = b"\x00\x01\x02\x03"

    relay = VoiceRelay(
        db,
        provider=FakeVoiceProvider([ChannelReady(), AgentAudio(frame)]),
        client=client,
    )
    await relay.run(session_id=session.id)

    assert client.sent == [frame]


async def test_what_the_panel_says_also_reaches_the_phone_as_words(
    db, sessions, funded_account
):
    """The caption leg of the same utterance.

    Captions are in the v1 accessibility floor (`CLAUDE.md`), which makes this
    the difference between a product a deaf user can use and one they cannot —
    a voice-only interrogation offers them nothing otherwise.

    Asserted alongside the audio rather than in isolation because the two are
    one utterance arriving twice, and the failure worth catching is a relay that
    carries one and drops the other. Text goes out on its own channel method so
    the client never has to inspect a frame to know whether it is holding
    something to play or something to show.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    client = FakeClientChannel()
    frame = b"\x00\x01\x02\x03"
    line = "Where does that 40% come from?"

    relay = VoiceRelay(
        db,
        provider=FakeVoiceProvider(
            [
                ChannelReady(),
                AgentAudio(frame),
                AgentTranscript(line, speaker="The CFO"),
            ]
        ),
        client=client,
    )
    await relay.run(session_id=session.id)

    assert client.sent == [frame]
    # The name travels with the words. The live screen develops one tray per
    # seated archetype (`Product.md` §3.4) and cannot tell three identical
    # rectangles apart from text alone.
    assert client.captions == [("The CFO", line)]


async def test_the_panel_s_words_never_reach_the_logs(
    db, sessions, funded_account, caplog
):
    """A regression guard, written green on purpose, and it does have teeth.

    `CLAUDE.md` forbids transcript text in logs. The reason it needs a test at
    all is that this is the one sensitive value the redactor cannot save us
    from: secrets are caught by key name, and a transcript is just a string —
    indistinguishable from a session id or an end reason to anything scanning
    keys. The only thing keeping it out is that nobody passes it, which is
    exactly the kind of guarantee that decays the first time somebody adds a
    debug line while chasing a caption bug.

    Both surfaces are scanned, because a leak can arrive through either and the
    obvious assertion catches neither reliably: `caplog.text` renders only the
    message, while `get_logger` puts keyword context on `record.context` via
    `extra=`. A guard reading just the rendered text passes happily while the
    transcript sits in the context dict — which is precisely how it would be
    logged, since that is how every other value here is passed.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    secret = "Our margin assumption is 62% and the board has not seen it"

    with caplog.at_level(logging.DEBUG):
        await VoiceRelay(
            db,
            provider=FakeVoiceProvider(
                    [ChannelReady(), AgentTranscript(secret, speaker="The CFO")]
                ),
            client=FakeClientChannel(),
        ).run(session_id=session.id)

    logged = [caplog.text]
    for record in caplog.records:
        logged.append(record.getMessage())
        logged.extend(str(value) for value in getattr(record, "context", {}).values())

    assert not any("62%" in line for line in logged)
    assert not any(secret in line for line in logged)


async def test_what_the_user_says_reaches_the_provider(db, sessions, funded_account):
    """And the same in the other direction, which is the harder one.

    Outbound audio is just another event on a stream the relay was already
    reading. Inbound is a second source entirely — the phone speaks whenever it
    likes, not in reply to anything — so the relay has to pump both at once.
    That is why this is the test that introduces concurrency.

    The frames arrive as they were sent. Base64 is applied at the far leg only,
    because that is ElevenLabs' wire requirement rather than ours, and paying
    its 33% on our own leg would be bandwidth spent for nothing.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    spoken = [b"\x10\x11", b"\x12\x13"]

    provider = FakeVoiceProvider([ChannelReady()])
    relay = VoiceRelay(
        db, provider=provider, client=FakeClientChannel(inbound=spoken)
    )
    await relay.run(session_id=session.id)

    assert provider.channel.received == spoken


async def test_a_user_cutting_in_stops_the_panel_mid_sentence(
    db, sessions, funded_account
):
    """Barge-in, which is the feature ElevenLabs was chosen for (Product.md §5.1).

    Not merely observing the event. Audio travels ahead of playback — frames
    are already on the phone, buffered, when the user starts talking over them
    — so an interruption that only stopped *future* frames would leave the
    panelist finishing their sentence into someone who had already cut in. The
    room would not feel interruptible, which is the whole point of it.

    So the client is told to drop what it has not played yet. Everything sent
    before the interruption is spent; what matters is that the buffer goes.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    client = FakeClientChannel()

    relay = VoiceRelay(
        db,
        provider=FakeVoiceProvider(
            [ChannelReady(), AgentAudio(b"\xaa\xbb"), Interrupted()]
        ),
        client=client,
    )
    await relay.run(session_id=session.id)

    assert client.discarded == 1


async def test_a_user_who_loses_the_line_gets_a_room_that_waits(
    db, sessions, meter, ledger, funded_account
):
    """The socket dropping is no longer an ending — it opens the reconnect
    window (docs/reconnect.md). The room stays `active` under a stamp with
    its billable span closed, so nothing settles, nothing more is billed,
    and the reaper is the one who gives up on the presenter's behalf.

    The provider is held open so this test can only be won by one side. With
    both free to finish, which of them ended the conversation would be a race,
    and the end reason would be a coin toss.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await VoiceRelay(
        db, provider=FakeVoiceProvider([ChannelReady()]), client=FakeClientChannel()
    ).run(session_id=session.id)

    await mark_heard(db, session.id)
    await _running_for(db, session, seconds=60)
    await meter.sweep()
    charged = await ledger.balance(user_id=funded_account.user_id)

    hung_up = FakeClientChannel()
    hung_up.hang_up()
    await VoiceRelay(
        db,
        provider=FakeVoiceProvider([ChannelReady()], keep_open=True),
        client=hung_up,
    ).run(session_id=session.id)

    waiting = await sessions.get(session_id=session.id)
    assert waiting.state is SessionState.ACTIVE
    assert waiting.end_reason is None
    assert waiting.disconnected_at is not None

    # Unbilled from the stamp onward, and nothing refunded either — ticks are
    # charged in arrears, so the ledger was already right when the line went.
    await meter.sweep()
    assert (
        await ledger.balance(user_id=funded_account.user_id)
    ).total_seconds == charged.total_seconds


async def test_a_stale_relay_cannot_stamp_a_room_a_newer_socket_took_over(
    db, sessions, funded_account
):
    """The half-open case, at the relay's own seam. The phone reconnected —
    a newer connection claimed the room — and only then did the old socket's
    relay notice it was dead. Its stamp must be refused, or the live room
    stops billing and starts a reaper clock under its presenter."""
    import uuid as uuid_module

    stale = uuid_module.uuid4()
    session = await sessions.start(user_id=funded_account.user_id)
    await VoiceRelay(
        db,
        provider=FakeVoiceProvider([ChannelReady()]),
        client=FakeClientChannel(),
        connection_id=stale,
    ).run(session_id=session.id)

    # The reconnect wins the race: a newer socket now speaks for the room.
    await sessions.connection_opened(
        session_id=session.id, connection_id=uuid_module.uuid4()
    )

    hung_up = FakeClientChannel()
    hung_up.hang_up()
    await VoiceRelay(
        db,
        provider=FakeVoiceProvider([], keep_open=True),
        client=hung_up,
        connection_id=stale,
    ).run(session_id=session.id)

    live = await sessions.get(session_id=session.id)
    assert live.state is SessionState.ACTIVE
    assert live.disconnected_at is None


async def _capped_by_the_meter(db, sessions, meter, funded_account):
    """A room the meter has already closed, with the relay still attached.

    The race the two tests below are about, set up through the real meter rather
    than by writing a state onto the row: what makes this hard is that the
    session was ended by a *different* caller in a different pass, and a test
    that forged the end state would not exercise that.

    Ended at the session cap specifically, because that ending refunds nothing
    and is not the ending either relay path would choose. If the relay overwrote
    it, the assertion would catch it — an idle timeout would not, since that is
    a reason the relay itself can produce.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await VoiceRelay(
        db, provider=FakeVoiceProvider([ChannelReady(), UserSpoke()]), client=FakeClientChannel()
    ).run(session_id=session.id)

    await _running_for(db, session, seconds=int(SESSION_LIMIT.total_seconds()))
    await meter.sweep()

    capped = await sessions.get(session_id=session.id)
    assert capped.state is SessionState.SETTLED
    assert capped.end_reason is EndReason.SESSION_CAP
    return session


async def test_a_room_closed_under_the_relay_ends_quietly_when_the_phone_hangs_up(
    db, sessions, meter, funded_account
):
    """The meter got there first, and the phone dropping is no longer news.

    This is ordinary traffic, not a fault: the meter closes a room at its cap
    while the socket is still up, the client keeps streaming for a moment, and
    then the user closes the app. Two callers, one room, and the second one
    arrives to find nothing left to do.

    Raising here is wrong twice over. The socket would close under
    `CLOSE_PROVIDER_UNAVAILABLE`, so a room that ended perfectly normally at its
    own cap would reach the phone as an outage — and the relay's `_end` would be
    reporting a state machine refusal as though the room had failed. The state
    machine is right to refuse; the relay is wrong to ask.
    """
    session = await _capped_by_the_meter(db, sessions, meter, funded_account)

    hung_up = FakeClientChannel()
    hung_up.hang_up()
    await VoiceRelay(
        db, provider=FakeVoiceProvider([], keep_open=True), client=hung_up
    ).run(session_id=session.id)

    unchanged = await sessions.get(session_id=session.id)
    assert unchanged.state is SessionState.SETTLED
    assert unchanged.end_reason is EndReason.SESSION_CAP


async def test_a_room_closed_under_the_relay_still_reports_the_provider_failing(
    db, sessions, meter, funded_account
):
    """The mirror case, and the reason this is not simply swallowed.

    The provider breaking is the one thing on this path worth surfacing — it is
    what `run` re-raises for, and what the router turns into
    `CLOSE_PROVIDER_UNAVAILABLE`. If `_end` raises on its way out, that failure
    is replaced by a state machine refusal, and the vendor outage becomes
    invisible in exactly the incident where somebody is looking for it.

    So the relay stops trying to end a room somebody else already ended, and
    changes nothing about what it re-raises.
    """
    session = await _capped_by_the_meter(db, sessions, meter, funded_account)

    relay = VoiceRelay(db, provider=DyingVoiceProvider([]), client=FakeClientChannel())
    with pytest.raises(ProviderUnavailable):
        await relay.run(session_id=session.id)

    unchanged = await sessions.get(session_id=session.id)
    assert unchanged.end_reason is EndReason.SESSION_CAP


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
    await VoiceRelay(db, provider=FakeVoiceProvider([ChannelReady()]), client=FakeClientChannel()).run(
        session_id=session.id
    )
    await _last_heard_from(db, session, seconds=int(ORPHAN_TIMEOUT.total_seconds()) + 10)

    await VoiceRelay(db, provider=FakeVoiceProvider([Heartbeat()]), client=FakeClientChannel()).run(
        session_id=session.id
    )
    await reaper.reap()

    still_running = await sessions.get(session_id=session.id)
    assert still_running.state is SessionState.ACTIVE
    assert still_running.end_reason is None


async def test_a_room_that_ends_normally_leaves_a_recording(
    db, sessions, storage, funded_account
):
    """The whole audio path, from two sockets to one object.

    The relay is the only place this can happen. All three signals pass through
    it — the user's audio on one task, the panel's and `Interrupted` on the
    other — and settlement cannot do it: `meter.py:186` closes a room that hits
    its cap while the socket is still up, from a loop that never held a mixer.
    That is the *longest* room, and the one most worth keeping.
    """
    session = await sessions.start(user_id=funded_account.user_id)

    relay = VoiceRelay(
        db,
        provider=FakeVoiceProvider([ChannelReady(), AgentAudio(b"\x10\x00" * 800)]),
        client=FakeClientChannel([b"\x20\x00" * 800]),
        recordings=RoomRecordings(storage),
    )
    await relay.run(session_id=session.id)

    saved = await storage.get(recording_key(session.id))
    assert saved is not None
    # An MP4 opens with a box length then "ftyp" (the container decision of
    # 2026-09-01: iPhones cannot play Ogg).
    assert saved[4:8] == b"ftyp"

    # Both sources actually reached the mix. The container magic alone proves
    # only that *something* was encoded — mutation testing showed it passes with
    # either side unplugged, which is the whole failure this is guarding.
    #
    # Membership rather than an exact buffer, because the two arrive on separate
    # tasks: whether they overlap (summing to 48) or fall clear of each other is
    # a scheduling detail, and asserting it would test asyncio.
    samples = array.array("h", relay._mixer.mixed())
    assert any(sample in (32, 48) for sample in samples), "no user audio"
    assert any(sample in (16, 48) for sample in samples), "no panel audio"


async def test_a_room_that_failed_leaves_nothing_behind(
    db, sessions, storage, funded_account
):
    """A refunded room is one the product has said did not happen.

    `docs/session-retention.md` discards audio on the fail path, and the rule is
    derived rather than restated: `REFUND_REASONS` already lists the endings
    that give the user their money back, so "we refunded it" and "there is
    nothing to keep" cannot drift apart into two lists that disagree.
    """
    session = await sessions.start(user_id=funded_account.user_id)

    relay = VoiceRelay(
        db,
        provider=DyingVoiceProvider([ChannelReady(), AgentAudio(b"\x10\x00" * 800)]),
        client=FakeClientChannel([b"\x20\x00" * 800]),
        recordings=RoomRecordings(storage),
    )
    with pytest.raises(ProviderUnavailable):
        await relay.run(session_id=session.id)

    assert await storage.get(recording_key(session.id)) is None


async def test_a_room_the_meter_ended_as_idle_keeps_nothing(
    db, sessions, settlement, storage, funded_account
):
    """The refund check, actually exercised — the test above does not reach it.

    A provider failure re-raises out of `run` before the save is attempted, so
    `test_a_room_that_failed_leaves_nothing_behind` proves nothing about
    `REFUND_REASONS`; mutation testing showed it passes with that check deleted.

    This is the case that needs it, and the one the wiring exists for. `meter.py`
    can close a room *while the socket is still open* — so the relay reaches its
    save with a room already settled and already refunded, and the end reason is
    the only thing left that knows it should keep nothing.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await sessions.activate(session_id=session.id)
    await settlement.close(session_id=session.id, end_reason=EndReason.IDLE_TIMEOUT)

    relay = VoiceRelay(
        db,
        provider=FakeVoiceProvider([AgentAudio(b"\x10\x00" * 800)]),
        client=FakeClientChannel([b"\x20\x00" * 800]),
        recordings=RoomRecordings(storage),
    )
    await relay.run(session_id=session.id)

    assert relay._mixer.mixed() != b"", "the room was recorded"
    assert await storage.get(recording_key(session.id)) is None, "but not kept"


async def test_the_recording_drops_what_the_phone_was_told_to_drop(
    db, sessions, storage, funded_account
):
    """`Interrupted` has to reach the mixer, not only the socket.

    The relay's answer to barge-in is `discard_playback` — the phone throws away
    buffered frames nobody will hear. If the recording does not make the same
    cut, the saved room has a panelist talking over the user for the seconds
    they were silenced, which is the defect the mixer exists to prevent and is
    trivially reintroduced here by handling the event on one side only.

    Asserted on the mixer rather than by decoding the object, because the claim
    is about which samples were kept, and Opus is lossy — a decoded comparison
    would be testing the codec.
    """
    session = await sessions.start(user_id=funded_account.user_id)

    relay = VoiceRelay(
        db,
        provider=FakeVoiceProvider(
            [ChannelReady(), AgentAudio(b"\x10\x00" * 400), Interrupted()]
        ),
        client=FakeClientChannel(),
        recordings=RoomRecordings(storage),
    )
    await relay.run(session_id=session.id)

    # The user never spoke, so the clock never advanced and every panel sample
    # was still unplayed when the interruption landed.
    assert relay._mixer.mixed() == b""


async def test_the_phone_is_told_when_the_floor_comes_back(
    db, sessions, funded_account
):
    """The turn is over, forwarded rather than left for the phone to infer.

    Its own channel method, like the caption and the barge-in before it: the
    client never inspects a payload to know what it is holding. And its own
    frame rather than a flag on the caption, because the caption arrives
    *before* the audio it captions — a floor announced there would invite the
    presenter to talk over the whole question.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    client = FakeClientChannel()

    relay = VoiceRelay(
        db,
        provider=FakeVoiceProvider(
            [
                ChannelReady(),
                AgentAudio(b"\x00\x01"),
                AgentFinished(),
            ]
        ),
        client=client,
    )
    await relay.run(session_id=session.id)

    assert client.yielded == 1

