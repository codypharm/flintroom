"""The ticket that admits one socket to one room."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VoiceTicket(Base):
    """A short-lived, single-use credential for one session's stream.

    Exists because a WebSocket handshake cannot carry an `Authorization` header
    from a browser, and CLAUDE.md forbids assumptions a web client would have
    to unpick later. The alternative was putting the access token in the query
    string, which writes a long-lived credential into every access log between
    here and the client.

    Everything about the shape follows from where the value gets written down.
    It is single-use, so a ticket recovered from a log has already been spent.
    It expires in seconds, so one recovered before use is still worthless. And
    it grants exactly one room, so it is not a credential in any broader sense
    — losing it cannot cost the user anything but this connection.
    """

    __tablename__ = "voice_tickets"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    #: SHA-256 of the ticket, never the ticket — the same reasoning as
    #: `refresh_tokens.token_hash`. The input is 32 bytes of `secrets` output,
    #: so there is no dictionary to run and nothing a slow KDF would buy.
    ticket_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    #: The one room this admits to. A ticket is not a general credential, and
    #: binding it here is what keeps a leaked one from being pointed at another
    #: session.
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        # Cascading, unlike most of this schema: a ticket has no meaning once
        # its room is gone, and it holds nothing worth keeping for evidence.
        # What a ticket did is in the log and, where it mattered, in
        # `audit_events` — which deliberately has no foreign keys at all.
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: Who the socket turns out to be. There is no header to read on the far
    #: side, so this row is the identity and not merely the permission.
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    #: Set by the redeeming UPDATE itself rather than by a read followed by a
    #: write. Two sockets racing the same ticket both match the row, but only
    #: one update finds `redeemed_at` still null — so single-use is enforced by
    #: Postgres rather than by the order our statements happen to run in.
    redeemed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
