"""What a session endpoint needs before it runs.

The services are built with the caller already attached, so there is no route in
the module that can reach session state without a user — the same reasoning
`CLAUDE.md` gives for authentication being a dependency rather than a check
inside a service.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import SessionNotFound
from app.core.logging import get_logger
from app.modules.auth.dependencies import CallerContext, CurrentUser
from app.modules.sessions.models import Session
from app.modules.ingestion.dependencies import ObjectStorageDep
from app.modules.sessions.preferences import PreferenceService
from app.modules.sessions.retention import RecordingRetention
from app.modules.sessions.service import SessionService
from app.modules.sessions.settlement import SettlementService

log = get_logger(__name__, tag="sessions")


async def get_session_service(
    caller: CallerContext,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionService:
    """A service that audits everything it does as this caller.

    Provenance is set at construction rather than passed per call, so a handler
    cannot attribute half its writes to the user and half to the system.
    """
    return SessionService(db, actor=caller)


SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]


async def get_settlement_service(
    caller: CallerContext,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SettlementService:
    """Settlement, attributed to the user who asked for it.

    The same writes the meter and the reaper make, under a different actor —
    which is the point of recording one: "who closed this room" is the first
    question asked of a session that settled unexpectedly.
    """
    return SettlementService(db, actor=caller)


SettlementServiceDep = Annotated[SettlementService, Depends(get_settlement_service)]


async def get_owned_session(
    session_id: uuid.UUID, user_id: CurrentUser, sessions: SessionServiceDep
) -> Session:
    """Resolve the session named in the path, for the caller who owns it.

    Not found rather than forbidden. A 403 would confirm that the id names a
    real session, which is the only thing an attacker guessing ids is trying to
    learn — and the caller's next move is identical either way.

    Logged as a denial, because it is one: an id in a URL that belongs to
    somebody else is either a bug in a client or someone probing, and neither
    leaves any other trace (`CLAUDE.md` → deny by default, log the denial).
    """
    session = await sessions.get(session_id=session_id)
    if session.user_id != user_id:
        log.warning(
            "session_access_denied",
            user_id=str(user_id),
            session_id=str(session_id),
        )
        raise SessionNotFound(session_id=str(session_id), user_id=str(user_id))
    return session


#: Every route that names a session in its path annotates with this instead of
#: taking a raw `session_id`, so ownership is resolved once, before the handler,
#: and no endpoint can be added that forgets it.
OwnedSession = Annotated[Session, Depends(get_owned_session)]


async def get_preference_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PreferenceService:
    """Choices, which are not audited as an actor's writes.

    No `CallerContext`, unlike the services either side of it: this writes no
    money and no audit row, and the log line it emits already names the user.
    """
    return PreferenceService(db)


PreferenceServiceDep = Annotated[PreferenceService, Depends(get_preference_service)]


async def get_recording_retention(
    caller: CallerContext,
    db: Annotated[AsyncSession, Depends(get_db)],
    storage: ObjectStorageDep,
) -> RecordingRetention:
    """Deleting a room's audio, attributed to whoever asked.

    The sweep builds this with no actor and lands as SYSTEM. Through a request
    it is the user, which is what makes "the window expired" and "this person
    asked" distinguishable in `audit_events` afterwards.
    """
    return RecordingRetention(db, storage, actor=caller)


RecordingRetentionDep = Annotated[
    RecordingRetention, Depends(get_recording_retention)
]
