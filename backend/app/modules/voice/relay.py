"""The relay — a provider's event stream driving the session state machine.

Thin by intent. Everything it does is call a `SessionService` method that
already exists and is already tested; what this adds is the wiring that decides
*which* one, and when. The seams it drives (`activate`, and shortly `fail`,
`record_speech`, `record_progress`) were cut for exactly this caller when the
state machine was built, and had none until now.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.errors import ProviderUnavailable
from app.core.logging import get_logger
from app.modules.sessions.schemas import EndReason, SessionState
from app.modules.sessions.service import SessionService
from app.modules.sessions.settlement import SettlementService
from app.modules.voice.events import (
    AgentAudio,
    ChannelReady,
    Heartbeat,
    UserSpoke,
    VoiceEvent,
)
from app.modules.voice.provider import ClientChannel, VoiceChannel, VoiceProvider

log = get_logger(__name__, tag="voice")


class VoiceRelay:
    """Pumps one session's channel until the provider has nothing left to say."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        provider: VoiceProvider,
        client: ClientChannel,
        actor: ActorContext | None = None,
    ) -> None:
        self._provider = provider
        self._client = client
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
                if await self._pump(channel, session_id=session_id):
                    await self._end(
                        session_id=session_id, live=EndReason.CLIENT_DISCONNECT
                    )
        except ProviderUnavailable:
            await self._end(session_id=session_id, live=EndReason.PROVIDER_FAILURE)
            raise

    async def _pump(self, channel: VoiceChannel, *, session_id: uuid.UUID) -> bool:
        """Carry both directions at once, and stop as soon as either ends.

        Two tasks rather than one loop because the phone talks whenever it
        likes rather than in reply to anything — a single loop would have to
        finish reading one side before looking at the other, which on a live
        conversation is exactly the stall the latency budget cannot afford.

        Whichever side finishes first ends the conversation, and the other is
        cancelled. Waiting for both instead would hang the relay whenever the
        provider hung up while the user was still holding a quiet line open:
        the room would stay on the provider's invoice with nothing left to
        deliver, which is the failure the whole session-cap machinery exists to
        prevent from happening slowly.
        """
        from_client = asyncio.create_task(self._carry_user_audio(channel))
        from_provider = asyncio.create_task(
            self._carry_provider_events(channel, session_id)
        )
        done, pending = await asyncio.wait(
            {from_client, from_provider}, return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()
        # Awaited rather than abandoned: a cancelled task nobody collects is
        # reported at interpreter exit, long after the context that would have
        # explained it is gone.
        await asyncio.gather(*pending, return_exceptions=True)

        for task in done:
            # Re-raises whatever ended the conversation — in particular a
            # provider failure, which `run` translates into the right ending.
            task.result()

        # Which side hung up decides how the room ends, and whether anything is
        # refunded. Answered by identity rather than by a flag either coroutine
        # sets, because a flag written from inside a task that is about to be
        # cancelled is a race with its own cancellation.
        return from_client in done

    async def _carry_user_audio(self, channel: VoiceChannel) -> None:
        async for pcm in self._client.audio():
            await channel.send_audio(pcm)

    async def _carry_provider_events(
        self, channel: VoiceChannel, session_id: uuid.UUID
    ) -> None:
        async for event in channel.events():
            await self._handle(event, session_id=session_id)

    async def _end(self, *, session_id: uuid.UUID, live: EndReason) -> None:
        """End a room that stopped, by whichever route its state allows.

        The two routes are not interchangeable, and the state machine enforces
        that: a session still in `provisioning` never billed anything and moves
        straight to `failed`, while one that reached `active` has a meter
        running behind it and must settle — which is what triggers whatever
        refund `REFUND_REASONS` maps for the reason given.

        A room that never opened always ends as `provisioning_failed`, whatever
        took it down. What ended a room that did not exist is not a distinction
        the cost reports can use, and recording `client_disconnect` there would
        put a session nobody was ever charged for among the ones that were.

        Reading the state rather than remembering whether we saw `ChannelReady`
        keeps the two from disagreeing. The database is the authority on whether
        the room ever opened; a flag on this object is a second answer that can
        drift from it.
        """
        session = await self._sessions.get(session_id=session_id)
        if session.state is SessionState.PROVISIONING:
            await self._sessions.fail(session_id=session_id)
            return

        await self._settlement.close(session_id=session_id, end_reason=live)

    async def _handle(self, event: VoiceEvent, *, session_id: uuid.UUID) -> None:
        if isinstance(event, ChannelReady):
            await self._sessions.activate(session_id=session_id)
        elif isinstance(event, UserSpoke):
            await self._sessions.record_speech(session_id=session_id)
        elif isinstance(event, Heartbeat):
            await self._sessions.record_progress(session_id=session_id)
        elif isinstance(event, AgentAudio):
            # Straight through. The relay does no codec work in either
            # direction — that is what the PCM-throughout transport decision
            # bought, and re-encoding here would put decode latency into the
            # path the ~1.5s illusion threshold is measured across.
            await self._client.send_audio(event.pcm)
