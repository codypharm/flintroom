"""How long a room can be heard again, and proving it stopped.

`docs/session-retention.md` splits the two artefacts a session leaves behind:
the transcript lives for the life of the account on every tier, and the audio
lives on a per-tier window. Only one of them compounds.

The window is also the sentence the privacy policy has to contain
(Open Risk #5), which is why it is enforced by something that leaves a record
rather than by a bucket rule that leaves none.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import func, select, update

from datetime import timedelta

from app.modules.audit_log.models import AuditEvent
from app.modules.audit_log.schemas import AuditEventType
from app.modules.sessions.models import Session as SessionModel
from app.modules.sessions.schemas import SessionState
from app.modules.sessions.models import SessionRecording
from app.modules.sessions.retention import RecordingRetention
from app.modules.voice.recording import RoomRecordings, recording_key
from app.modules.billing.tiers import (
    FREE_TIER,
    MONTHLY_ALLOWANCE_SECONDS,
    RECORDING_RETENTION_DAYS,
)

pytestmark = pytest.mark.asyncio


async def _settled_days_ago(db, session_id, *, days: int) -> None:
    """Age a room, using the database's clock rather than Python's.

    The sweep compares `settled_at` against `now()` inside the query, so a
    timestamp written from here would be comparing two machines' clocks — the
    same trap `db_now` exists to avoid.
    """
    await db.execute(
        update(SessionModel)
        .where(SessionModel.id == session_id)
        # Both, because `ck_sessions_settled_at` enforces that settled and
        # timestamped are the same fact — a room with one and not the other is a
        # state the database refuses to hold, and rightly.
        .values(
            state=SessionState.SETTLED,
            settled_at=func.now() - timedelta(days=days),
        )
    )
    await db.commit()


async def test_every_tier_says_how_long_it_keeps_a_room():
    """A tier with no window would keep audio forever by omission.

    The failure mode is silence rather than an error: a new tier added to the
    price list and not to this table gets no expiry, accrues indefinitely, and
    contradicts a published promise — with nothing anywhere raising.

    Free is included explicitly. It is absent from `MONTHLY_ALLOWANCE_SECONDS`
    because its grant is lifetime rather than renewing, but it still records
    rooms, so it still needs a window.
    """
    assert set(RECORDING_RETENTION_DAYS) == {FREE_TIER, *MONTHLY_ALLOWANCE_SECONDS}


async def test_the_windows_are_the_ones_the_architect_chose():
    """30 / 90 / 365, decided 2026-08-17.

    Pinned deliberately. `Product.md` §413 listed the recording-retention window
    under "Undecided, do not invent" until this was settled, and these numbers
    land on tier cards — so a change is a pricing change, and it should have to
    break a test that names the decision rather than pass quietly.
    """
    assert RECORDING_RETENTION_DAYS == {
        "free": 30,
        "starter": 90,
        "pro": 365,
        "pro_annual": 365,
        "teams": 90,
    }


async def test_saving_a_room_records_that_it_exists(
    db, sessions, storage, funded_account
):
    """The sweep cannot find what nothing wrote down.

    A deterministic key means the object could in principle be located without a
    row — but "which rooms are past their window" is a question about owners,
    tiers and settlement times, and none of that is in a key. Asking the store
    instead would mean listing a bucket to answer a question the database
    already holds.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await db.commit()

    await RoomRecordings(storage, db=db).save(
        session_id=session.id, pcm=b"\x10\x00" * 16_000
    )

    stored = await db.get(SessionRecording, session.id)
    assert stored is not None
    assert stored.byte_size > 0
    assert stored.deleted_at is None


async def test_a_room_past_its_window_is_deleted_and_the_deletion_is_provable(
    db, sessions, storage, funded_account
):
    """Both halves, because either alone is worthless.

    Deleting without a record is what a bucket lifecycle rule already does, and
    `docs/session-retention.md` rejected exactly that: a bucket policy is a
    *configuration*, not evidence that one user's audio is gone. Recording
    without deleting is a promise on a page.

    A free account here, so the window is thirty days.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await db.commit()
    await RoomRecordings(storage, db=db).save(
        session_id=session.id, pcm=b"\x10\x00" * 16_000
    )
    assert await storage.get(recording_key(session.id)) is not None

    await _settled_days_ago(db, session.id, days=31)
    await RecordingRetention(db, storage).sweep()

    assert await storage.get(recording_key(session.id)) is None
    assert (await db.get(SessionRecording, session.id)).deleted_at is not None


async def test_a_room_inside_its_window_is_left_alone(
    db, sessions, storage, funded_account
):
    """The sweep runs every pass, so this is the case it meets almost always.

    A predicate that was slightly too eager would delete recordings a user is
    still entitled to, at a rate nobody would notice until somebody complained
    that last week's room had gone.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await db.commit()
    await RoomRecordings(storage, db=db).save(
        session_id=session.id, pcm=b"\x10\x00" * 16_000
    )

    await _settled_days_ago(db, session.id, days=29)
    await RecordingRetention(db, storage).sweep()

    assert await storage.get(recording_key(session.id)) is not None
    assert (await db.get(SessionRecording, session.id)).deleted_at is None


async def test_a_downgrade_shortens_the_window_on_rooms_already_recorded(
    db, sessions, storage, funded_account
):
    """The case that decided the mechanism.

    `docs/session-retention.md` rejected a bucket lifecycle rule largely on this:
    a Pro account with year-old rooms that drops to Free would need every object
    re-tagged or moved for a rule to be correct, and nothing would do it.

    Reading the tier inside the sweep makes it fall out for free. A hundred-day
    old room is inside Pro's year and well past Free's thirty days, so the same
    row expires or does not purely according to who the account is *now*.
    """
    funded_account.entitlement_tier = "pro"
    await db.commit()

    session = await sessions.start(user_id=funded_account.user_id)
    await db.commit()
    await RoomRecordings(storage, db=db).save(
        session_id=session.id, pcm=b"\x10\x00" * 16_000
    )
    await _settled_days_ago(db, session.id, days=100)

    await RecordingRetention(db, storage).sweep()
    assert await storage.get(recording_key(session.id)) is not None, "kept on pro"

    funded_account.entitlement_tier = FREE_TIER
    await db.commit()

    await RecordingRetention(db, storage).sweep()
    assert await storage.get(recording_key(session.id)) is None, "gone on free"


async def test_an_empty_pass_still_says_it_ran(db, storage, caplog):
    """Silence is the alert, so the quiet pass is the one that must speak.

    `docs/deployment.md` makes the *absence* of a sweep's line the signal,
    because nothing raises when a loop stops running. A sweep that logged only
    when it found work would look identical to a sweep that had died — and of
    the sweeps in this process, this is the one whose silence means audio is
    outliving a published promise rather than money going uncollected.
    """
    with caplog.at_level(logging.INFO):
        await RecordingRetention(db, storage).sweep()

    assert "recordings_swept" in caplog.text


async def test_an_expired_room_is_only_expired_once(
    db, sessions, storage, funded_account
):
    """The sweep runs every fifteen seconds, forever, over a table that grows.

    Deleting an object that is already gone succeeds, so a predicate that
    forgot to exclude already-deleted rows would look perfectly healthy: the
    audio is gone, the timestamp is set, every other test passes. Mutation
    testing found exactly that hole.

    What it would actually do is re-expire every room ever recorded on every
    pass — one duplicate `recording_expired` row each, four times a minute,
    into an append-only table. The audit trail is the deliverable here, and one
    filled with thousands of restatements of the same deletion is not evidence
    of anything.

    Asserted on the audit rows rather than on `deleted_at`, because a restamped
    timestamp is invisible and a duplicated row is the actual harm.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await db.commit()
    await RoomRecordings(storage, db=db).save(
        session_id=session.id, pcm=b"\x10\x00" * 16_000
    )
    await _settled_days_ago(db, session.id, days=31)

    await RecordingRetention(db, storage).sweep()
    await RecordingRetention(db, storage).sweep()
    await RecordingRetention(db, storage).sweep()

    expiries = await db.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.event_type == AuditEventType.RECORDING_EXPIRED,
            AuditEvent.session_id == session.id,
        )
    )
    assert expiries.scalar_one() == 1
