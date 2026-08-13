"""The relay — a provider's event stream driving the session state machine.

Thin by intent. Everything it does is call a `SessionService` method that
already exists and is already tested; what this adds is the wiring that decides
*which* one, and when. The seams it drives (`activate`, and shortly `fail`,
`record_speech`, `record_progress`) were cut for exactly this caller when the
state machine was built, and had none until now.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.errors import ProviderUnavailable
from app.core.logging import get_logger
from app.modules.sessions.schemas import EndReason, SessionState
from app.modules.sessions.service import SessionService
from app.modules.sessions.settlement import SettlementService
from app.modules.voice.events import ChannelReady, Heartbeat, UserSpoke, VoiceEvent
from app.modules.voice.provider import VoiceProvider

log = get_logger(__name__, tag="voice")


class VoiceRelay:
    """Pumps one session's channel until the provider has nothing left to say."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        provider: VoiceProvider,
        actor: ActorContext | None = None,
    ) -> None:
        self._provider = provider
        self._actor = actor or ActorContext.system()
        # Built here rather than injected, for the reason `SessionService` gives
        # for its own audit service: every write this relay causes is attributed
        # to the actor the relay was constructed with, and a caller cannot hand
        # in a service that attributes them to somebody else.
        self._sessions = SessionService(db, self._actor)
        self._settlement = SettlementService(db, self._actor)

    async def run(self, *, session_id: uuid.UUID) -> None:
        """Open a channel for this session and handle what comes back.

        A provider that cannot be dialled leaves the session `failed` rather
        than stranded in `provisioning`. Stranded is not merely untidy: a
        provisioning session still holds the one-active-session lock, so the
        user would be unable to start another room until the reaper swept it.

        Re-raised after marking, because the caller still has a socket to close
        and a status to report. What it must not do is name the vendor.
        """
        try:
            async with self._provider.open() as channel:
                async for event in channel.events():
                    await self._handle(event, session_id=session_id)
        except ProviderUnavailable:
            await self._abandon(session_id=session_id)
            raise

    async def _abandon(self, *, session_id: uuid.UUID) -> None:
        """End a room the provider took down, by whichever route it is owed.

        The two endings are not interchangeable, and the state machine enforces
        that: a session still in `provisioning` never billed anything and moves
        straight to `failed`, while one that reached `active` has a meter
        running behind it and must settle — which is what triggers the refund
        `REFUND_REASONS` maps for a provider failure.

        Reading the state rather than remembering whether we saw `ChannelReady`
        keeps the two from disagreeing. The database is the authority on whether
        the room ever opened; a flag on this object is a second answer that can
        drift from it.
        """
        session = await self._sessions.get(session_id=session_id)
        if session.state is SessionState.PROVISIONING:
            await self._sessions.fail(session_id=session_id)
            return

        await self._settlement.close(
            session_id=session_id, end_reason=EndReason.PROVIDER_FAILURE
        )

    async def _handle(self, event: VoiceEvent, *, session_id: uuid.UUID) -> None:
        if isinstance(event, ChannelReady):
            await self._sessions.activate(session_id=session_id)
        elif isinstance(event, UserSpoke):
            await self._sessions.record_speech(session_id=session_id)
        elif isinstance(event, Heartbeat):
            await self._sessions.record_progress(session_id=session_id)
