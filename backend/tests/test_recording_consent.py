"""Saying that rooms are saved, and letting somebody stop it.

`docs/session-retention.md` decided saving is **on by default, disclosed up
front**: OS microphone permission means "we may hear you", not "we keep it",
and what stores require for a recording the user is themselves making is
disclosure and control rather than opt-in.

Control is the half that has to exist in code. A disclosure that points at a
setting which does nothing is worse than no disclosure at all.
"""

from __future__ import annotations

import pytest

from sqlalchemy import func, select

from app.modules.audit_log.models import AuditEvent
from app.modules.audit_log.schemas import AuditEventType
from app.modules.sessions.models import SessionRecording
from app.modules.sessions.preferences import PreferenceService
from app.modules.sessions.retention import RecordingRetention
from app.modules.voice.events import AgentAudio, ChannelReady
from app.modules.voice.recording import RoomRecordings, recording_key
from app.modules.voice.relay import VoiceRelay
from tests.fakes import FakeClientChannel, FakeVoiceProvider

pytestmark = pytest.mark.asyncio


async def test_rooms_are_saved_unless_somebody_says_otherwise(db, funded_account):
    """On by default, and answered without a row existing.

    Nobody writes a preference at signup — that would be a row per account for
    a value every account shares. So the default has to be the *absence* of a
    row, and a service that returned False for a user who never chose would
    silently switch the feature off for everybody who has not visited Settings.
    """
    preferences = PreferenceService(db)

    assert await preferences.records_rooms(user_id=funded_account.user_id) is True


async def test_turning_saving_off_is_remembered(db, funded_account):
    preferences = PreferenceService(db)

    await preferences.set_records_rooms(
        user_id=funded_account.user_id, enabled=False
    )

    assert await preferences.records_rooms(user_id=funded_account.user_id) is False


async def test_turning_it_back_on_does_not_need_a_second_row(db, funded_account):
    """Idempotent by construction, because the toggle is a toggle.

    A user flipping this twice is ordinary, and an insert-only implementation
    would fail on the second write with a primary key violation — a 500 on the
    Settings screen, from the control that exists to reassure them.
    """
    preferences = PreferenceService(db)

    await preferences.set_records_rooms(user_id=funded_account.user_id, enabled=False)
    await preferences.set_records_rooms(user_id=funded_account.user_id, enabled=True)

    assert await preferences.records_rooms(user_id=funded_account.user_id) is True


async def test_a_room_started_with_saving_off_is_not_recorded(
    db, sessions, storage, funded_account, session_factory
):
    """The switch has to be wired to something.

    Checked when the room is built rather than when it is saved, so a user who
    turned recording off never has their voice held in memory for the length of
    an interrogation — the preference is about whether we keep audio, and the
    least surprising reading of "off" is that we do not accumulate it either.
    """
    await PreferenceService(db).set_records_rooms(
        user_id=funded_account.user_id, enabled=False
    )
    session = await sessions.start(user_id=funded_account.user_id)
    await db.commit()

    relay = VoiceRelay(
        db,
        provider=FakeVoiceProvider([ChannelReady(), AgentAudio(b"\x10\x00" * 800)]),
        client=FakeClientChannel([b"\x20\x00" * 800]),
        recordings=RoomRecordings(storage, db=db),
        records=False,
    )
    await relay.run(session_id=session.id)

    assert relay._mixer.mixed() == b"", "nothing was accumulated"
    assert await storage.get(recording_key(session.id)) is None
    # #69. Recording off stops the *keeping*, never the clock. The gate used to
    # sit around `self._mixer.heard(pcm)` in the relay, which stopped both — and
    # the mixer is what a transcript line's offset is read from, so every line
    # in a room like this one would have claimed to begin at second zero. The
    # transcript is kept on every tier regardless of this preference, so those
    # lines exist and would have been confidently wrong.
    assert relay._mixer.elapsed() > 0, "the room still knew what time it was"


async def test_deleting_a_room_removes_the_audio_and_leaves_the_proof(
    db, sessions, storage, funded_account
):
    """A user asking is the other way audio goes, besides the window expiring.

    Same shape as the sweep, and deliberately: object first, row second, an
    audit line either way. `docs/session-retention.md` chose an application
    sweep over a bucket rule so deletion could be *proved*, and a deletion
    somebody explicitly requested is the one most likely to be asked about.

    The transcript is untouched. The two artefacts have separate lifetimes by
    design, and deleting the audio must not silently take the debrief's
    grounding with it.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await db.commit()
    await RoomRecordings(storage, db=db).save(
        session_id=session.id, pcm=b"\x10\x00" * 16_000
    )

    await RecordingRetention(db, storage).delete(session_id=session.id)

    assert await storage.get(recording_key(session.id)) is None
    assert (await db.get(SessionRecording, session.id)).deleted_at is not None

    expiries = await db.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.session_id == session.id)
    )
    assert expiries.scalar_one() >= 1


async def test_deleting_a_room_twice_is_not_an_error(
    db, sessions, storage, funded_account
):
    """A second tap on a slow connection must not be a 500.

    `CLAUDE.md` lists duplicate actions as a case every feature handles
    explicitly, and a delete button is where it actually happens — the first
    request is still in flight, the row already says deleted, and the honest
    answer is that the thing they asked for is true.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await db.commit()
    await RoomRecordings(storage, db=db).save(
        session_id=session.id, pcm=b"\x10\x00" * 16_000
    )

    await RecordingRetention(db, storage).delete(session_id=session.id)
    first = (await db.get(SessionRecording, session.id)).deleted_at

    await RecordingRetention(db, storage).delete(session_id=session.id)

    # Not merely "no exception" — that passes with the guard deleted, because
    # removing an absent object succeeds and the row simply gets restamped.
    # Mutation testing caught exactly that. What a second delete must not do is
    # move the timestamp that is the evidence, or add a second row claiming the
    # same audio was destroyed twice.
    assert (await db.get(SessionRecording, session.id)).deleted_at == first

    deletions = await db.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.event_type == AuditEventType.RECORDING_DELETED,
            AuditEvent.session_id == session.id,
        )
    )
    assert deletions.scalar_one() == 1


async def test_the_preference_says_how_long_rooms_are_kept(db, funded_account):
    """The disclosure has to state a window, and nothing else can tell it one.

    `docs/session-retention.md` requires the first-session sheet to say how long
    rooms are kept, and the windows are per tier. No endpoint exposed a tier —
    `GET /v1/me` answers only whether the credential is good — so a client could
    disclose "we keep your rooms" and nothing truthful after it.

    It rides the recording preference rather than getting an endpoint of its
    own, because the two are one question asked in two halves: whether we record
    you, and for how long we keep it.
    """
    preferences = PreferenceService(db)

    assert await preferences.retention_days(user_id=funded_account.user_id) == 30

    funded_account.entitlement_tier = "pro"
    await db.commit()

    assert await preferences.retention_days(user_id=funded_account.user_id) == 365
