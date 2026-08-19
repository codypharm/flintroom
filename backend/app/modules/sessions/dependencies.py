"""What a session endpoint needs before it runs.

The services are built with the caller already attached, so there is no route in
the module that can reach session state without a user — the same reasoning
`CLAUDE.md` gives for authentication being a dependency rather than a check
inside a service.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ProviderUnavailable, SessionNotFound
from app.core.logging import get_logger
from app.modules.auth.dependencies import CallerContext, CurrentUser
from app.modules.sessions.models import Session
from app.modules.ingestion.dependencies import ObjectStorageDep
from app.agents.coach import CoachModel
from app.agents.weakness import WeaknessReader
from app.modules.sessions.coaching import CoachService
from app.modules.sessions.debrief import DebriefService
from app.modules.sessions.progress import ProgressService
from app.modules.sessions.preferences import PreferenceService
from app.modules.sessions.retention import RecordingRetention
from app.modules.sessions.service import SessionService
from app.modules.sessions.settlement import SettlementService
from app.modules.voice.dictation import Dictation
from app.modules.voice.speech import Speaker

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


async def get_progress_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProgressService:
    """A read, and only a read.

    No `CallerContext` for the same reason `PreferenceService` has none: it
    writes nothing, moves no money and leaves no audit row. It is arithmetic
    over rooms that were already assessed.
    """
    return ProgressService(db)


ProgressServiceDep = Annotated[ProgressService, Depends(get_progress_service)]


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


def get_weakness_reader(request: Request) -> WeaknessReader:
    """The process-wide reader, built once in the application lifespan.

    A deployment without model credentials fails here rather than at boot, on
    the same grounds as the object store: auth, balances, the room and the
    transcript all work without one. What is lost is the debrief's ranked list,
    which `Product.md` §3.5 calls *"the part users will pay for"* — so the
    failure is loud at the point of use and logged once at startup, rather than
    silent in either place.

    Vendor-anonymous, as `CLAUDE.md` requires: the client learns that the
    debrief is unavailable, not which model vendor we buy.
    """
    reader = getattr(request.app.state, "weakness_reader", None)
    if reader is None:
        log.error("weakness_reader_unconfigured")
        raise ProviderUnavailable(reason="debrief_unconfigured")
    return reader


WeaknessReaderDep = Annotated[WeaknessReader, Depends(get_weakness_reader)]


async def get_debrief_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    reader: WeaknessReaderDep,
) -> DebriefService:
    """Reading a finished room, once."""
    return DebriefService(db, reader=reader)


DebriefServiceDep = Annotated[DebriefService, Depends(get_debrief_service)]


def get_dictation(request: Request) -> Dictation:
    """The process-wide transcriber for one-shot clips.

    Missing means the debrief can be read but not spoken to — the ranked list is
    a different seam and still works — so it fails here, typed and
    vendor-anonymous, rather than at boot.
    """
    dictation = getattr(request.app.state, "dictation", None)
    if dictation is None:
        log.error("dictation_unconfigured")
        raise ProviderUnavailable(reason="dictation_unconfigured")
    return dictation


def get_coach_model(request: Request) -> CoachModel:
    """The process-wide coach."""
    coach = getattr(request.app.state, "coach_model", None)
    if coach is None:
        log.error("coach_model_unconfigured")
        raise ProviderUnavailable(reason="coach_unconfigured")
    return coach


def get_speaker(request: Request) -> Speaker:
    """The voice the coach speaks in.

    **The expressive one, and this is where it is cheapest.** #34 measured the
    slower model at 0.39s to first byte and twice the credits per character —
    the first price is what keeps it off interrogation turns, and the debrief
    does not pay it: `docs/debrief-and-sparring.md` decision 5 makes coaching
    turn-based HTTP rather than a live socket, so nobody is sitting in a room
    waiting on it.

    Falls back to the room's own synthesiser when no expressive one is
    configured, so a deployment with one voice still coaches.
    """
    speaker = getattr(request.app.state, "expressive_speaker", None) or getattr(
        request.app.state, "speaker", None
    )
    if speaker is None:
        log.error("speaker_unconfigured")
        raise ProviderUnavailable(reason="speech_unconfigured")
    return speaker


async def get_coach_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    debrief: DebriefServiceDep,
    dictation: Annotated[Dictation, Depends(get_dictation)],
    coach: Annotated[CoachModel, Depends(get_coach_model)],
    speaker: Annotated[Speaker, Depends(get_speaker)],
) -> CoachService:
    """One spoken turn of the debrief, end to end."""
    return CoachService(
        db, dictation=dictation, coach=coach, speaker=speaker, debrief=debrief
    )


CoachServiceDep = Annotated[CoachService, Depends(get_coach_service)]
