"""Wiring for the voice module."""

from typing import Annotated

from fastapi import Depends, Request, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ProviderUnavailable
from app.core.logging import get_logger
from app.modules.voice.provider import VoiceProvider
from app.modules.voice.tickets import VoiceTicketService

log = get_logger(__name__, tag="voice")


async def get_ticket_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VoiceTicketService:
    return VoiceTicketService(db)


VoiceTicketServiceDep = Annotated[VoiceTicketService, Depends(get_ticket_service)]


def get_voice_provider(websocket: WebSocket) -> VoiceProvider:
    """The process-wide provider, built once in the application lifespan.

    Read off application state rather than constructed here, for the same
    reason the auth verifiers are: one instance per process. A provider built
    per connection would rebuild dialling state on every room, and this is the
    object that will hold pooling and per-archetype voice configuration.

    An unconfigured deployment fails here rather than at boot — see
    `Settings.elevenlabs_api_key`. Loudly and typed: the relay ends the room,
    the client is told the room is over, and nobody learns which vendor is
    missing.
    """
    provider = getattr(websocket.app.state, "voice_provider", None)
    if provider is None:
        log.error("voice_provider_unconfigured")
        raise ProviderUnavailable(reason="provider_unconfigured")
    return provider


VoiceProviderDep = Annotated[VoiceProvider, Depends(get_voice_provider)]
