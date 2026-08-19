"""Wiring for the voice module."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, WebSocket
from starlette.requests import HTTPConnection
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.auditor import ClaimReader
from app.agents.model import PanelModel
from app.core.database import get_db
from app.core.logging import get_logger
from app.modules.voice.recording import RoomRecordings
from app.modules.voice.speech import Speaker
from app.modules.voice.tickets import VoiceTicketService
from app.modules.voice.transcription import Transcriber

log = get_logger(__name__, tag="voice")


async def get_ticket_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VoiceTicketService:
    return VoiceTicketService(db)


VoiceTicketServiceDep = Annotated[VoiceTicketService, Depends(get_ticket_service)]


@dataclass(frozen=True, slots=True)
class RoomParts:
    """The process-wide half of a room, read off application state.

    A room is built from two halves. These four are per process and built once
    in the lifespan, for the reason the auth verifiers are: each holds
    connection state, and rebuilding them per socket would pay that cost on
    every interrogation. The other half — who is seated, what may be attacked —
    is per session and comes from the database in `build_room`.

    Carried as one object rather than three dependencies because they are always
    wanted together and always come from the same place. Three would be three
    chances to read one off the wrong state.

    Absent parts are carried rather than refused here. Whether a missing one
    ends the room is `build_room`'s call, and it answers differently for each: a
    room with no transcriber or no model cannot work, while a room with no
    speaker is merely silent and one with no claim reader merely never notices a
    figure moving.
    """

    transcriber: Transcriber | None
    model: PanelModel | None
    speaker: Speaker | None
    #: The opener's voice. Optional and separate: `OrchestratedChannel` falls
    #: back to `speaker`, so a deployment with one synthesiser still opens out
    #: loud — it just does so without the expressiveness.
    opener_speaker: Speaker | None = None

    #: Stateless and process-wide, unlike the `Auditor` built around it — that
    #: accumulates one session's figures and is made per stream in
    #: `OrchestratedProvider.open`.
    reader: ClaimReader | None = None


def get_room_parts(websocket: WebSocket) -> RoomParts:
    """Whatever this deployment was configured with."""
    state = websocket.app.state
    return RoomParts(
        transcriber=getattr(state, "transcriber", None),
        model=getattr(state, "panel_model", None),
        speaker=getattr(state, "speaker", None),
        opener_speaker=getattr(state, "expressive_speaker", None),
        reader=getattr(state, "claim_reader", None),
    )


RoomPartsDep = Annotated[RoomParts, Depends(get_room_parts)]


def get_room_recordings(connection: HTTPConnection) -> RoomRecordings | None:
    """Somewhere to save a finished room, if this deployment has one.

    `None` rather than a refusal, unlike `ingestion`'s storage dependency which
    raises. The difference is what each one is for: a deck that cannot be
    uploaded is a request that failed, while a room that cannot be recorded is a
    rehearsal that still happened. Refusing the socket would trade an entire
    interrogation for a missing file.

    `HTTPConnection` rather than `Request`, for the reason `get_db` documents at
    length: a WebSocket is not a `Request`, and asking for one dies in dependency
    resolution before any of our code runs.
    """
    storage = getattr(connection.app.state, "object_storage", None)
    if storage is None:
        log.warning("room_recordings_unconfigured")
        return None
    return RoomRecordings(storage)


RoomRecordingsDep = Annotated[RoomRecordings | None, Depends(get_room_recordings)]
