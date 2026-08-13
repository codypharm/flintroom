"""Minting and spending stream tickets.

The refusals here are deliberately indistinguishable to the caller. Expired,
already spent, never issued, and issued for a different room all raise the same
`NotAuthenticated` with no detail — the same silence `RefreshTokenService.sign_out`
keeps, and for the same reason: a caller holding a string it should not have
must not be able to learn anything about it by presenting it.

The reason is recorded in the log, where the operator can see it and the
attacker cannot.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import db_now
from app.core.errors import NotAuthenticated
from app.core.logging import get_logger
from app.modules.voice.models import VoiceTicket

log = get_logger(__name__, tag="voice")

#: How long the client has to get its socket open.
#:
#: Short because the value travels in a query string, which is written to access
#: logs, proxy logs and browser history. The window only has to cover the gap
#: between the response to `POST /sessions` and the handshake that follows it —
#: a client that cannot manage that in half a minute has worse problems than
#: authentication.
TICKET_TTL = timedelta(seconds=30)

#: 32 bytes of `secrets` output, matching `refresh.TOKEN_BYTES`. Unguessable, so
#: the stored hash needs no salt and no slow KDF.
TICKET_BYTES = 32


def _hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode()).hexdigest()


class VoiceTicketService:
    """Issues tickets at session start, and spends them at connect."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def mint(self, *, session_id: uuid.UUID, user_id: uuid.UUID) -> str:
        """A ticket admitting one socket to one room, once."""
        ticket = secrets.token_urlsafe(TICKET_BYTES)
        now = await db_now(self._db)
        self._db.add(
            VoiceTicket(
                ticket_hash=_hash(ticket),
                session_id=session_id,
                user_id=user_id,
                expires_at=now + TICKET_TTL,
            )
        )
        await self._db.commit()
        return ticket

    async def redeem(self, *, ticket: str, session_id: uuid.UUID) -> uuid.UUID:
        """Spend a ticket for this room and answer who holds it.

        One statement, not a read followed by a write. Every condition that
        makes a ticket unusable — spent, expired, wrong room — is in the WHERE
        clause, so two sockets racing the same ticket contend on the row and
        exactly one of them comes back with a result. Checking in Python first
        would leave a window in which both had seen it unspent.
        """
        result = await self._db.execute(
            update(VoiceTicket)
            .where(
                VoiceTicket.ticket_hash == _hash(ticket),
                VoiceTicket.session_id == session_id,
                VoiceTicket.redeemed_at.is_(None),
                VoiceTicket.expires_at > func.now(),
            )
            .values(redeemed_at=func.now())
            .returning(VoiceTicket.user_id)
        )
        user_id = result.scalar_one_or_none()
        await self._db.commit()

        if user_id is None:
            # Deliberately without saying which condition failed. The operator
            # gets the session id and can reconstruct it; the caller gets
            # nothing it did not already know.
            log.warning("voice_ticket_rejected", session_id=str(session_id))
            raise NotAuthenticated(session_id=str(session_id))

        return user_id
