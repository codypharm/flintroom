"""Wiring for the voice module."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.voice.tickets import VoiceTicketService


async def get_ticket_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VoiceTicketService:
    return VoiceTicketService(db)


VoiceTicketServiceDep = Annotated[VoiceTicketService, Depends(get_ticket_service)]
