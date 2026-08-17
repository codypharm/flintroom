"""Session endpoints.

Thin, per `CLAUDE.md`: parse the request, call a service, return a response.
"""

from fastapi import APIRouter, Depends, status

from app.core.errors import RecordingNotAvailable
from app.core.storage_s3 import DEFAULT_EXPIRY_SECONDS
from app.modules.auth.dependencies import CurrentUser, rate_limit_user
from app.modules.ingestion.dependencies import ObjectStorageDep
from app.modules.voice.recording import recording_key
from app.modules.auth.rate_limit import SESSION_START_LIMIT
from app.modules.sessions.dependencies import (
    PreferenceServiceDep,
    RecordingRetentionDep,
    OwnedSession,
    SessionServiceDep,
    SettlementServiceDep,
)
from app.modules.sessions.schemas import (
    RecordingPreference,
    RecordingPlayback,
    RecordingState,
    EndReason,
    SessionRead,
    SessionStart,
    SessionStarted,
)
from app.modules.voice.dependencies import VoiceTicketServiceDep

router = APIRouter(tags=["sessions"])


@router.post(
    "/sessions",
    response_model=SessionStarted,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_user("session_start", SESSION_START_LIMIT))],
)
async def start_session(
    user_id: CurrentUser,
    sessions: SessionServiceDep,
    tickets: VoiceTicketServiceDep,
    body: SessionStart | None = None,
) -> SessionStarted:
    """Open a room for the caller, and hand them the key to its stream.

    The user is taken from the credential, never from the body: a client that
    could name the account would be able to spend somebody else's minutes.

    Two service calls rather than one, and still no rules here — the sequence
    carries no branch and no condition, so nothing about *when* a room may open
    has leaked out of `SessionService`. If the mint ever grows a decision, it
    belongs behind a service of its own, as settlement did for the join between
    sessions and the ledger.

    A mint that failed after the start committed would leave the caller holding
    a room they cannot connect to and unable to open another until the reaper
    clears it, roughly a minute later. Both statements run on the same
    connection against the same database, so the case is nearly always "the
    database is gone", where the start would not have committed either.
    """
    session = await sessions.start(
        user_id=user_id,
        material_ids=body.material_ids if body else [],
        archetypes=body.archetypes if body else [],
    )
    return SessionStarted(
        **(await _read(session, sessions)).model_dump(),
        stream_ticket=await tickets.mint(session_id=session.id, user_id=user_id),
    )


@router.get("/sessions/{session_id}", response_model=SessionRead)
async def read_session(
    session: OwnedSession, sessions: SessionServiceDep
) -> SessionRead:
    """One session, if it belongs to the caller."""
    return await _read(session, sessions)


@router.get("/preferences/recording", response_model=RecordingPreference)
async def read_recording_preference(
    user_id: CurrentUser, preferences: PreferenceServiceDep
) -> RecordingPreference:
    """Whether rooms are being saved for this account."""
    return RecordingPreference(
        records_rooms=await preferences.records_rooms(user_id=user_id)
    )


@router.put("/preferences/recording", response_model=RecordingPreference)
async def set_recording_preference(
    body: RecordingPreference,
    user_id: CurrentUser,
    preferences: PreferenceServiceDep,
) -> RecordingPreference:
    """Turn saving on or off for future rooms.

    `PUT` rather than `POST`, because this sets a value rather than appending
    one — the second identical request is the same state, which is exactly what
    a toggle tapped twice on a slow connection produces.

    Affects rooms started after this. Existing recordings are deliberately left
    alone: they were made under a disclosure the user accepted, and destroying
    them as a side effect of a switch would be a surprise in the one direction
    that cannot be undone. Deleting a room is its own explicit action, below.
    """
    await preferences.set_records_rooms(
        user_id=user_id, enabled=body.records_rooms
    )
    return body


@router.delete(
    "/sessions/{session_id}/recording", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_recording(
    session: OwnedSession, retention: RecordingRetentionDep
) -> None:
    """Destroy one room's audio, because the user asked.

    204 whether or not there was anything there. `CLAUDE.md` lists duplicate
    actions as a case to handle rather than a 500, and a second tap is asking
    for something already true — answering 404 would tell somebody their
    deletion failed at the moment it had in fact succeeded.

    The transcript survives. The two artefacts have separate lifetimes by
    design, and this must not quietly take the debrief's grounding with it.
    """
    await retention.delete(session_id=session.id)


@router.get(
    "/sessions/{session_id}/recording", response_model=RecordingPlayback
)
async def play_recording(
    session: OwnedSession,
    sessions: SessionServiceDep,
    storage: ObjectStorageDep,
) -> RecordingPlayback:
    """A link to hear one room again.

    Plays the stored object. ElevenLabs is never called and no credits are
    consumed — re-synthesising a room costs about a hundred times what storing
    it does, and could not reproduce the user's own voice at any price.

    Ownership is settled by `OwnedSession` before this body runs, and the
    recording's state is checked before a URL is asked for. `core/storage.py`
    says why that order matters: signing is not a permission check, and that
    layer signs whatever it is told to sign.

    Refuses rather than signing a key that is not there. A URL to an absent
    object is a link that reaches the store, fails there, and leaves the client
    reading somebody else's error page — and the state is already published on
    the session, so a well-behaved client never arrives here at all.
    """
    recording = await sessions.recording(session_id=session.id)
    if recording.state is not RecordingState.AVAILABLE:
        raise RecordingNotAvailable(
            context={"session_id": str(session.id), "state": recording.state.value}
        )

    return RecordingPlayback(
        url=storage.presign_get(recording_key(session.id)),
        expires_in_seconds=DEFAULT_EXPIRY_SECONDS,
    )


@router.post("/sessions/{session_id}/end", response_model=SessionRead)
async def end_session(
    session: OwnedSession,
    settlement: SettlementServiceDep,
    sessions: SessionServiceDep,
) -> SessionRead:
    """The End button: an intent, honoured by the server.

    The end reason is not taken from the body. `user_ended` is the only ending
    a client is in a position to report, and every other reason in the enum
    decides whether minutes are refunded — a client that could name one would
    be choosing its own refund.
    """
    return await _read(
        await settlement.close(session_id=session.id, end_reason=EndReason.USER_ENDED),
        sessions,
    )


async def _read(session, sessions: SessionServiceDep) -> SessionRead:
    """A session with the grounding it was started against, and the room in it.

    Two extra queries rather than eager relationships on `Session`. The sweeps
    that run every fifteen seconds select columns instead of rows, so they would
    not pay for it — but `_active_session` does load a row, on every single
    start, to answer a question that has nothing to do with either. Paying there
    for something only three responses read is the wrong place to spend it.

    Assembly, not a rule: no branch, no condition, nothing about *what* may
    ground a room or sit in it has leaked out of `SessionService`.
    """
    panel = await sessions.panel(session_id=session.id)
    return SessionRead.model_validate(session).model_copy(
        update={
            "material_ids": await sessions.materials(session_id=session.id),
            "recording": await sessions.recording(session_id=session.id),
            "archetypes": [archetype.name for archetype in panel],
        }
    )
