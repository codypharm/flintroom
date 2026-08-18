"""One spoken turn of the debrief, answered.

The assembly `docs/debrief-and-sparring.md` decision 5 describes: a clip
arrives, is heard, reaches a coach that can only talk about this session, and
comes back as words and a voice. No socket, no meter, no reaper — the phone is
in the user's hand here, not face-down on a desk, and there is no clock to beat.

**Both halves of the answer are returned.** `CLAUDE.md` sets the accessibility
floor at WCAG 2.2 AA *plus live captions*, as a v1 requirement rather than a
later addition, so a reply that was only audio would be unusable for part of the
audience — and a client cannot caption bytes it was handed.

Nothing here decides what may be said. That is `agents/coach.py`, and keeping
the two apart is deliberate: this module knows about databases and audio, and
the fence has to be readable without either.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.coach import COACH, CoachModel, Grounds, Spoken, held, spoken
from app.agents.context import USER
from app.core.errors import FlintroomError
from app.core.logging import get_logger
from app.modules.sessions.debrief import DebriefService
from app.modules.sessions.models import CoachTurn, TranscriptLine
from app.modules.voice.dictation import Dictation
from app.modules.voice.speech import Speaker
from app.agents.context import Said

log = get_logger(__name__, tag="debrief")


class NothingWasSaid(FlintroomError):
    """The clip held no speech.

    Somebody tapped record and said nothing, or the microphone was muted.
    Answering it would spend a model call having the coach respond to silence,
    which reads as a coach talking to itself — so it is refused before the coach
    is asked, with something a client can act on.

    Not a provider failure. The transcriber worked perfectly; there was nothing
    to hear.
    """

    code = "nothing_was_said"
    status_code = 422
    message = "I didn't catch anything there — try again."


@dataclass(frozen=True, slots=True)
class CoachedTurn:
    """What the user hears, and what they read while hearing it."""

    text: str
    speech: bytes


class CoachService:
    """Holds the coaching conversation for one room."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        dictation: Dictation,
        coach: CoachModel,
        speaker: Speaker,
        debrief: DebriefService,
    ) -> None:
        self._db = db
        self._dictation = dictation
        self._coach = coach
        self._speaker = speaker
        self._debrief = debrief

    async def say(
        self, *, session_id: uuid.UUID, clip: bytes, media_type: str
    ) -> CoachedTurn:
        """Hear one turn and answer it."""
        heard = await self._dictation.hear(clip, media_type=media_type)
        if not heard.text:
            raise NothingWasSaid(session_id=str(session_id))

        grounds = await self._grounds(session_id)
        exchange = (*await self._thread(session_id), Spoken(who=USER, text=heard.text))

        reply = await self._coach.reply(grounds=grounds, exchange=exchange)
        said = spoken(reply, grounds)

        log.info(
            "coach_turn",
            session_id=str(session_id),
            heard_seconds=heard.seconds,
            cited=len(held(reply, grounds)),
            redirected=said != reply.text,
            input_tokens=reply.usage.input_tokens,
            output_tokens=reply.usage.output_tokens,
        )

        await self._keep(session_id, heard.text, said)
        return CoachedTurn(text=said, speech=await self._voice(said))

    async def _grounds(self, session_id: uuid.UUID) -> Grounds:
        """Everything §405 lets the coach have an opinion about.

        Always through `DebriefService`, never by reading the table directly.
        That call is idempotent — it returns the stored list without a model
        call once one exists — so routing every turn through it costs nothing
        and buys the case that would otherwise be missed: a phone that jumps
        straight to the microphone without opening the list first. A coach
        handed no weak answers would be poorer for no reason, and the reason
        would be which screen the user happened to tap.

        It also means the debrief's refusals apply here. A room the provider
        broke, or one the panel never spoke in, cannot be coached either — and
        that falls out rather than being restated.
        """
        return Grounds(
            transcript=await self._transcript(session_id),
            weak_answers=await self._debrief.weak_answers(session_id=session_id),
        )

    async def _transcript(self, session_id: uuid.UUID) -> tuple[Said, ...]:
        """The room, in order, both sides.

        By `ordinal` and never `said_at`: lines are written as they are said, so
        two can share a clock reading, and a coach citing "line 4" against a
        transposed transcript would quote the wrong person.
        """
        rows = await self._db.execute(
            select(TranscriptLine)
            .where(TranscriptLine.session_id == session_id)
            .order_by(TranscriptLine.ordinal)
        )
        return tuple(
            Said(speaker=row.speaker, text=row.text, disputed=row.disputed)
            for row in rows.scalars()
        )

    async def _thread(self, session_id: uuid.UUID) -> tuple[Spoken, ...]:
        """The coaching conversation so far, oldest first."""
        rows = await self._db.execute(
            select(CoachTurn)
            .where(CoachTurn.session_id == session_id)
            .order_by(CoachTurn.ordinal)
        )
        return tuple(Spoken(who=row.who, text=row.text) for row in rows.scalars())

    async def _keep(self, session_id: uuid.UUID, asked: str, answered: str) -> None:
        """Both sides of the turn, in one transaction.

        **What is kept is what the user heard**, not what the model wanted to
        say. A thread holding the intended text of a redirected turn would hand
        the next turn a history in which the coach did the thing it refused to
        do — and it would reasonably carry on. The fence would hold once and
        leak into every turn afterwards.
        """
        ordinal = len(await self._thread(session_id))

        self._db.add_all(
            (
                CoachTurn(
                    session_id=session_id, ordinal=ordinal, who=USER, text=asked
                ),
                CoachTurn(
                    session_id=session_id,
                    ordinal=ordinal + 1,
                    who=COACH,
                    text=answered,
                ),
            )
        )
        await self._db.commit()

    async def _voice(self, text: str) -> bytes:
        """The reply, spoken.

        Collected rather than streamed, and this is the one place the debrief
        deliberately differs from the room. There, streaming is the barge-in
        requirement: a panelist stops because the consumer stops iterating. Here
        nobody interrupts the coach — the phone is in their hand and the turn is
        already over — so a whole answer over one request is simpler than a
        socket held open for four seconds of speech.
        """
        return b"".join([frame async for frame in self._speaker.speak(text=text, voice=None)])
