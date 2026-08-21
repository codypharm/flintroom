"""Enforcing how long a room can still be heard.

`docs/session-retention.md` chose an application sweep over a bucket lifecycle
rule, and the reasoning is worth keeping next to the code because the bucket
rule is the obvious answer and is wrong here for specific reasons:

- **Tier changes.** A Pro account with year-old rooms that drops to Free needs
  every object re-tagged or moved for a lifecycle rule to be correct. A sweep
  reading the tier at sweep time is simply right, with nothing to migrate.
- **Evidence.** An erasure request needs a completion record. A bucket policy is
  a *configuration* — it says what should happen, not that it happened to one
  user's audio. `session_recordings.deleted_at` says that.
- **It runs in development.** MinIO and R2 do not agree about lifecycle rules,
  so a rule would be untested until production, on the one mechanism whose
  failure is a privacy incident rather than a bug.

A generous lifecycle rule still belongs underneath this as a backstop, so a dead
sweep cannot retain audio indefinitely. It must never become load-bearing — the
same shape as RLS sitting behind service-role access in `CLAUDE.md`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.logging import get_logger
from app.core.storage import ObjectStorage
from app.modules.audit_log.schemas import AuditEventType
from app.modules.audit_log.service import AuditService
from app.modules.billing.models import Account
from app.modules.billing.tiers import FREE_TIER, RECORDING_RETENTION_DAYS
from app.modules.sessions.models import Session, SessionRecording
from app.modules.voice.recording import recording_key

log = get_logger(__name__, tag="sessions")

#: How many rooms one pass will expire.
#:
#: Each one is a network round trip to the object store, and the sweep shares a
#: pass with the meter — which writes money and must not be kept waiting behind
#: a backlog of deletions. A batch that does not clear is simply met again on
#: the next pass, so the only thing a cap costs is time, and only when a large
#: cohort expires together.
BATCH = 100


class RecordingRetention:
    """Removes room audio that has outlived its tier's window."""

    def __init__(
        self,
        db: AsyncSession,
        storage: ObjectStorage,
        actor: ActorContext | None = None,
    ) -> None:
        self._db = db
        self._storage = storage
        # Provenance at construction, never per call (`CLAUDE.md`). It is the
        # difference between "the window expired" and "this user asked", which
        # is the first question a privacy request asks — and a service that
        # could be told per call could answer it wrongly.
        #
        # Defaults to SYSTEM, which is what the sweep is.
        self._audit = AuditService(db, actor)

    async def sweep(self) -> None:
        """Expire one batch of rooms, and say so even when there are none.

        The empty pass is logged deliberately. `docs/deployment.md` makes the
        *absence* of a sweep's line the alert signal, because nothing raises
        when a loop stops running — and of all the sweeps here, this is the one
        whose silence is a privacy incident rather than a cost.
        """
        expired = await self._expired()

        for recording, session_id in expired:
            await self._remove(recording, session_id, AuditEventType.RECORDING_EXPIRED)

        await self._db.commit()
        log.info("recordings_swept", expired=len(expired))

    async def delete(self, *, session_id: uuid.UUID) -> None:
        """Destroy one room's audio because somebody asked.

        The same path the sweep takes, on purpose. Two triggers, one removal:
        if a user-requested delete had its own implementation, the ordering and
        the audit row could drift apart from the scheduled one — and the whole
        argument for an application sweep over a bucket rule was that deletion
        is provable, which is worth least if the two kinds of proof differ.

        Silent on a room that has no audio, or none any more. `CLAUDE.md` lists
        duplicate actions as a case to handle rather than a 500, and here the
        second tap is asking for something already true. The transcript is
        untouched: the two artefacts have separate lifetimes by design, and this
        must not quietly take the debrief's grounding with it.
        """
        recording = await self._db.get(SessionRecording, session_id)
        if recording is None or recording.deleted_at is not None:
            return

        await self._remove(recording, session_id, AuditEventType.RECORDING_DELETED)
        await self._db.commit()

    async def _remove(
        self,
        recording: SessionRecording,
        session_id: uuid.UUID,
        why: AuditEventType,
    ) -> None:
        """Object first, row second, evidence either way.

        The order is the important part. A row marked deleted over an object
        that is still there is the failure that cannot be seen: nothing looks at
        that row again, and the audio outlives its window while the record says
        otherwise.

        Not a `ledger_entries` row — no money moves. This is proof that audio is
        gone, which is exactly what `audit_events` is for (`CLAUDE.md` -> Audit
        model).
        """
        await self._storage.delete(recording_key(session_id))
        recording.deleted_at = func.now()
        await self._audit.record(
            why, session_id=session_id, stored_bytes=recording.byte_size
        )

    async def _expired(self) -> list[tuple[SessionRecording, uuid.UUID]]:
        """Rooms whose audio is past the window their owner is on *now*.

        The tier is read at sweep time and joined per row, which is the whole
        argument for doing this in the application. A downgrade shortens the
        window on every room the account already has, and an upgrade lengthens
        it, with nothing to re-tag either way.

        Ages from `settled_at` rather than `stored_at`. They are within seconds
        of each other, but settlement is when the room ended as far as every
        other report in this system is concerned, and a retention window a user
        was told about should be measured from the same mark.
        """
        # Built as a CASE rather than arithmetic on a column, because the
        # windows live in Python (`billing/tiers.py`, where every other per-tier
        # figure lives) and must not be duplicated into SQL or a migration.
        days = _tier_days_case()

        rows = await self._db.execute(
            select(SessionRecording, Session.id)
            .join(Session, Session.id == SessionRecording.session_id)
            .join(Account, Account.user_id == Session.user_id)
            .where(
                SessionRecording.deleted_at.is_(None),
                Session.settled_at.is_not(None),
                Session.settled_at < func.now() - days,
            )
            .order_by(Session.settled_at)
            .limit(BATCH)
        )
        return [(recording, session_id) for recording, session_id in rows]


def _tier_days_case():
    """`RECORDING_RETENTION_DAYS`, as an interval the database can compare.

    Generated from the Python table rather than written out, so a tier added
    there cannot be missing here — the failure that would otherwise keep one
    tier's audio forever, silently, because a row simply never matches.

    An unknown tier falls back to the free window. Deny by default
    (`CLAUDE.md`): keeping a room too long is the error that cannot be undone,
    and deleting one early is visible and complainable.
    """
    from sqlalchemy import case, cast, literal
    from sqlalchemy.types import Interval

    whens = {
        tier: cast(literal(f"{days} days"), Interval)
        for tier, days in RECORDING_RETENTION_DAYS.items()
    }
    return case(
        *[(Account.entitlement_tier == tier, interval) for tier, interval in whens.items()],
        else_=cast(literal(f"{RECORDING_RETENTION_DAYS[FREE_TIER]} days"), Interval),
    )
