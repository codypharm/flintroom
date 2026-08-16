"""The relay — a provider's event stream driving the session state machine.

Thin by intent. Everything it does is call a `SessionService` method that
already exists and is already tested; what this adds is the wiring that decides
*which* one, and when. The seams it drives — `activate`, `fail`,
`record_speech`, `record_progress` — were cut for exactly this caller when the
state machine was built, and had none until now.

It is also the only place that knows both sides of a conversation at once,
which is why the audio path passes through here rather than around it: the
metering decisions all depend on who was talking and whether anything was
still arriving.
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
    AgentTranscript,
    ChannelReady,
    Heartbeat,
    Interrupted,
    Spent,
    UserSpoke,
    VoiceEvent,
)
from app.modules.voice.provider import ClientChannel, VoiceChannel, VoiceProvider
from app.modules.voice.spend import SpendRecorder

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
        # Telemetry, not money — see `SpendRecorder`. It carries no actor,
        # because a cost row records what a provider charged us rather than
        # anything a user or an operator did.
        self._spend = SpendRecorder(db)

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
        """Handle each event, and never abandon one halfway through a write.

        This task is routinely cancelled: the phone hanging up finishes the
        *other* side of `_pump`, which then cancels this one — and the moment a
        user is most likely to hang up is right after a panelist stopped
        speaking, which is also when this loop is most likely to be mid-write.

        Cancelling inside a database call leaves the session unusable, and the
        first thing to touch it afterwards is `_end`. So the visible symptom is
        not a lost telemetry row but **a room that fails to settle**, whose
        minutes are then decided by the reaper rather than by the ending the
        user actually gave it.

        Shielding alone is not enough and is worse than nothing: it lets the
        handler keep running *while* the cancellation propagates, so the write
        and `_end` land on the same session at once. The inner task has to be
        awaited to completion before the cancellation is re-raised.

        This delays cancellation by one handler rather than refusing it. Every
        handler here is a single short write; none can hold the room open.
        """
        async for event in channel.events():
            handling = asyncio.create_task(self._handle(event, session_id=session_id))
            try:
                await asyncio.shield(handling)
            except asyncio.CancelledError:
                # Ours to finish, not to abandon. Failures are suppressed rather
                # than raised: we are already on the way out, and the ending the
                # room deserves is decided by `_end` rather than by whatever the
                # last handler happened to hit.
                await asyncio.gather(handling, return_exceptions=True)
                raise

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

        A room that is already ending belongs to whoever ended it. The meter
        closes rooms at their cap while the socket is still up, and the reaper
        closes abandoned ones — so arriving to find nothing left to do is
        ordinary contention rather than a fault, and it is the mirror of the
        `FlintroomError` the meter's sweep already tolerates per room.

        Nothing is retried here. A session left `finalizing` by a settlement
        that died partway is the reaper's to finish, and a relay racing it would
        be a second writer on the money path for no gain.
        """
        session = await self._sessions.get(session_id=session_id)
        if session.state is SessionState.PROVISIONING:
            await self._sessions.fail(session_id=session_id)
            return

        if session.state is not SessionState.ACTIVE:
            # Logged rather than passed over in silence: this is also what a
            # relay ending a room twice would look like, and the two are only
            # distinguishable from the ending that is already recorded.
            log.info(
                "room_already_ended",
                session_id=str(session_id),
                state=session.state.value,
                end_reason=session.end_reason.value if session.end_reason else None,
                unrecorded=live.value,
            )
            return

        await self._settlement.close(session_id=session_id, end_reason=live)

    async def _handle(self, event: VoiceEvent, *, session_id: uuid.UUID) -> None:
        if isinstance(event, ChannelReady):
            await self._sessions.activate(session_id=session_id)
        elif isinstance(event, UserSpoke):
            await self._sessions.record_speech(session_id=session_id)
        elif isinstance(event, Spent):
            # What the providers charged for this turn. Never a ledger entry and
            # never a balance: the user is charged in minutes by the meter, and
            # nothing here may influence that. This is the other side of the
            # trade, and until it existed nothing in the system could contradict
            # the $0.12/min every margin in §4.4 assumes.
            await self._spend.record(
                session_id=session_id,
                stt_seconds=event.stt_seconds,
                llm_input_tokens=event.llm_input_tokens,
                llm_output_tokens=event.llm_output_tokens,
                tts_characters=event.tts_characters,
            )
        elif isinstance(event, Heartbeat):
            await self._sessions.record_progress(session_id=session_id)
        elif isinstance(event, AgentTranscript):
            # The caption for the audio above, and the only path it has to the
            # phone. Not logged: `CLAUDE.md` forbids transcript text in logs,
            # and no redaction rule can catch it, because it is indistinguishable
            # from any other string by key name.
            await self._client.send_transcript(event.text)
        elif isinstance(event, Interrupted):
            # Audio runs ahead of playback, so by now frames the panelist will
            # never get to finish are already buffered on the phone. Stopping
            # only what we have not sent yet would let them talk over the user
            # who just cut in — which is the room failing to be interruptible,
            # the one thing barge-in exists to deliver.
            await self._client.discard_playback()
        elif isinstance(event, AgentAudio):
            # Straight through. The relay does no codec work in either
            # direction — that is what the PCM-throughout transport decision
            # bought, and re-encoding here would put decode latency into the
            # path the ~1.5s illusion threshold is measured across.
            await self._client.send_audio(event.pcm)
