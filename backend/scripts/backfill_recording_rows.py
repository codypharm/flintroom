"""Put the rooms already in storage on the books. Run once, at deploy.

The 2026-09-02 finding (#121): `get_room_recordings` constructed
`RoomRecordings` without a database, so every settled room's audio landed in
storage with no `session_recordings` row. No row means no play button, a
retention sweep blind to audio it is supposed to expire, and — because the
container migration drives off the rows — `.ogg` objects from before the
2026-09-01 M4A switch that the migration could not see either.

This walks *sessions* rather than rows, which is what makes it able to find
what the rows do not know about: for every settled session it asks storage
whether `rooms/{id}.m4a` exists, transcodes a leftover `rooms/{id}.ogg` into
one first when that is all there is, and inserts the missing row.

`stored_at` is set to the session's `settled_at`, not to now. The retention
window is a promise about when audio goes away, and a backfill that restarted
every clock today would quietly extend the window for every room it touched.

Idempotent: a session that already has a row is skipped, so a crashed run is
re-run rather than reasoned about.

Run with the production environment (the same DATABASE_URL and R2 variables
the deployed service uses):

    railway run uv run python -m scripts.backfill_recording_rows
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.storage_s3 import build_object_storage
from app.modules.sessions.models import Session, SessionRecording
from app.modules.sessions.schemas import SessionState
from app.modules.voice.encoding import M4A_CONTENT_TYPE, from_m4a, to_m4a

log = get_logger(__name__, tag="voice")


async def backfill() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    storage = build_object_storage(settings)
    if storage is None:
        raise SystemExit("no object storage configured; run with the production environment")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        rows = await db.execute(
            select(Session.id, Session.settled_at)
            .where(Session.state == SessionState.SETTLED)
            .where(
                Session.id.notin_(select(SessionRecording.session_id))
            )
        )
        candidates = list(rows)

    booked = transcoded = absent = 0
    for session_id, settled_at in candidates:
        m4a_key = f"rooms/{session_id}.m4a"
        ogg_key = f"rooms/{session_id}.ogg"

        stored = await storage.get(m4a_key)
        if stored is None:
            ogg = await storage.get(ogg_key)
            if ogg is None:
                # Nothing in storage for this room — recording off, an empty
                # mix, or a refunded ending. Absence is the correct record.
                absent += 1
                continue
            stored = to_m4a(from_m4a(ogg))
            await storage.put(m4a_key, stored, content_type=M4A_CONTENT_TYPE)
            await storage.delete(ogg_key)
            transcoded += 1
            log.info("recording_transcoded", session_id=str(session_id))

        async with factory() as db:
            await db.execute(
                insert(SessionRecording)
                .values(
                    session_id=session_id,
                    byte_size=len(stored),
                    stored_at=settled_at,
                )
                .on_conflict_do_nothing(index_elements=["session_id"])
            )
            await db.commit()
        booked += 1
        log.info(
            "recording_row_backfilled",
            session_id=str(session_id),
            stored_bytes=len(stored),
        )

    log.info(
        "recording_rows_backfill_done",
        booked=booked,
        transcoded=transcoded,
        absent=absent,
    )
    await engine.dispose()


if __name__ == "__main__":
    configure_logging()
    asyncio.run(backfill())
