"""Move every stored room from Ogg/Opus to MP4/AAC. Run once, at deploy.

The 2026-09-01 container decision (#25): iPhones cannot play Ogg, so rooms
now settle as `rooms/{id}.m4a` and every read derives that key. Nothing
persists the old keys, which means an unmigrated `.ogg` is not "an old room
that still plays on Android" — it is an orphan playback cannot find,
retention cannot expire, and account deletion cannot destroy. Personal data
retained forever with nothing raising, which is the exact failure
`docs/account-deletion.md` exists to prevent. So this sweep is part of the
container change, not an optimisation after it.

Idempotent: a session whose `.ogg` is already gone is skipped, so a crashed
run is re-run rather than reasoned about. The `.ogg` is deleted only after
the `.m4a` is written, so a failure between the two leaves both rather than
neither.

Run with the production environment (the same DATABASE_URL and R2 variables
the deployed service uses):

    railway run uv run python -m scripts.migrate_recordings
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.storage_s3 import build_object_storage
from app.modules.sessions.models import SessionRecording
from app.modules.voice.encoding import M4A_CONTENT_TYPE, from_m4a, to_m4a

log = get_logger(__name__, tag="voice")


async def migrate() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    storage = build_object_storage(settings)
    if storage is None:
        raise SystemExit("no object storage configured; run with the production environment")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        rows = await db.execute(select(SessionRecording.session_id))
        session_ids = [row for (row,) in rows]

    moved = skipped = 0
    for session_id in session_ids:
        old_key = f"rooms/{session_id}.ogg"
        new_key = f"rooms/{session_id}.m4a"

        stored = await storage.get(old_key)
        if stored is None:
            skipped += 1
            continue

        # `from_m4a` opens any container PyAV can sniff, Ogg included; the
        # name says what it is *for*, not the only thing it can read.
        pcm = await asyncio.to_thread(from_m4a, stored)
        encoded = await asyncio.to_thread(to_m4a, pcm)

        await storage.put(new_key, encoded, content_type=M4A_CONTENT_TYPE)
        await storage.delete(old_key)
        moved += 1
        log.info("recording_migrated", session_id=str(session_id))

    log.info("recording_migration_done", moved=moved, skipped=skipped)
    await engine.dispose()


if __name__ == "__main__":
    configure_logging()
    asyncio.run(migrate())
