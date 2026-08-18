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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.coach import COACH, CoachModel, CoachReply, Grounds, Spoken, held, spoken
from app.agents.weakness import WeakAnswer
from app.agents.context import USER
from app.core.errors import FlintroomError
from app.core.logging import get_logger
from app.modules.sessions.debrief import DebriefService
from app.modules.sessions.models import CoachTurn, SparringAttempt, TranscriptLine
from app.modules.voice.dictation import Dictation, Heard
from app.modules.voice.spend import SpendRecorder
from app.modules.voice.speech import Speaker
from app.agents.context import Said

log = get_logger(__name__, tag="debrief")


class NoSuchWeakAnswer(FlintroomError):
    """That rank is not in this room's ranked list.

    404 rather than 422: the client asked for something that does not exist, and
    the likeliest cause is a rank held from a different session.

    Refused before the clip is transcribed. Hearing a re-answer to a question
    nobody asked would pay a vendor to produce a string with nowhere to put it.
    """

    code = "no_such_weak_answer"
    status_code = 404
    message = "That isn't one of the questions from this session."


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
    """What the user hears, what they read while hearing it, and what was heard.

    `heard` is the transcriber's reading of their own clip, carried back rather
    than dropped. It is what makes a vendor mishearing distinguishable from the
    coach disagreeing, and it is the middle term of a sparring record: the
    answer the room got, then this one, then what changed.
    """

    text: str
    speech: bytes
    heard: str


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
        spend: SpendRecorder | None = None,
    ) -> None:
        self._db = db
        self._dictation = dictation
        self._coach = coach
        self._speaker = speaker
        self._debrief = debrief
        # Built here rather than injected when absent, because there is nothing
        # to configure: it takes the same session and writes the same table the
        # relay already writes. A caller that had to supply one would be a
        # caller that could forget to.
        self._spend = spend or SpendRecorder(db)

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
        await self._spent(session_id, heard=heard, reply=reply, said=said)

        return CoachedTurn(
            text=said, speech=await self._voice(said), heard=heard.text
        )

    async def spar(
        self,
        *,
        session_id: uuid.UUID,
        weak_rank: int,
        clip: bytes,
        media_type: str,
    ) -> CoachedTurn:
        """Re-answer one question the room found weak, and hear what changed.

        **The question is chosen by rank, not described.** That is the anchor
        `docs/debrief-and-sparring.md` decision 4 requires rather than merely
        prefers: a re-answer is fresh speech, which is exactly the shape *"spar
        me on this instead"* would use to smuggle in a new pitch. Only a row
        that already exists is addressable, so there is no argument in which a
        different subject could be named.
        """
        weak = await self._weak(session_id, weak_rank)

        heard = await self._dictation.hear(clip, media_type=media_type)
        if not heard.text:
            raise NothingWasSaid(session_id=str(session_id))

        grounds = await self._grounds(session_id)
        attempts = (*await self._attempts(session_id, weak_rank), heard.text)

        reply = await self._coach.spar(
            grounds=grounds, weak=weak, attempts=attempts
        )
        said = spoken(reply, grounds)

        log.info(
            "sparring_attempt",
            session_id=str(session_id),
            weak_rank=weak_rank,
            attempt=len(attempts),
            heard_seconds=heard.seconds,
            redirected=said != reply.text,
            input_tokens=reply.usage.input_tokens,
            output_tokens=reply.usage.output_tokens,
        )

        self._db.add(
            SparringAttempt(
                session_id=session_id,
                weak_rank=weak_rank,
                attempt=len(attempts) - 1,
                said=heard.text,
                reply=said,
            )
        )
        await self._db.commit()
        await self._spent(session_id, heard=heard, reply=reply, said=said)

        return CoachedTurn(
            text=said, speech=await self._voice(said), heard=heard.text
        )

    async def _weak(self, session_id: uuid.UUID, rank: int) -> WeakAnswer:
        """The question at this rank, or a refusal.

        Read through `DebriefService` rather than off the table, so a room that
        has never been debriefed is read first and every refusal it makes —
        still running, no questions, provider broke it — applies here without
        being restated.
        """
        answers = await self._debrief.weak_answers(session_id=session_id)

        if not 0 <= rank < len(answers):
            raise NoSuchWeakAnswer(session_id=str(session_id), rank=rank)

        return answers[rank]

    async def _attempts(
        self, session_id: uuid.UUID, weak_rank: int
    ) -> tuple[str, ...]:
        """Every go at this question so far, oldest first."""
        rows = await self._db.execute(
            select(SparringAttempt)
            .where(
                SparringAttempt.session_id == session_id,
                SparringAttempt.weak_rank == weak_rank,
            )
            .order_by(SparringAttempt.attempt)
        )
        return tuple(row.said for row in rows.scalars())


    async def _spent(
        self, session_id: uuid.UUID, *, heard: Heard, reply: CoachReply, said: str
    ) -> None:
        """What this turn cost, on the row §4.3 reconciles against an invoice.

        Three vendors are paid per coaching turn — the transcriber hears the
        clip, the model answers, the synthesiser speaks — and the phase earns
        nothing. `docs/ingestion.md`'s framing for extraction applies unchanged:
        unmetered is not free, and a phase whose cost nobody counted is the one
        that quietly decides a margin.

        `said` rather than `reply.text`, deliberately: a redirected turn is
        synthesised as the redirect, so the characters actually sent to the
        synthesiser are the ones the user heard.
        """
        await self._spend.record(
            session_id=session_id,
            stt_seconds=int(heard.seconds),
            llm_input_tokens=reply.usage.input_tokens,
            llm_output_tokens=reply.usage.output_tokens,
            tts_characters=len(said),
        )
        await self._stayed(session_id)

    async def _stayed(self, session_id: uuid.UUID) -> None:
        """How long they have been at it, recomputed from the turns.

        No phase span is opened anywhere for coaching, and that is a decision
        rather than an omission. Turn-based transport left nothing to open a
        span around: there is no socket, so nothing bills for silence, and a
        span opened on a debrief read would never be closed — `open_phase`
        closes the current span only when a *new* phase opens, and after the
        debrief there is no next phase. The duration would grow without bound,
        which is worse than missing: a wrong number gets fixed and an unbounded
        one gets averaged into a price.

        The turn timestamps already answer the question, so they answer it.
        """
        await self._spend.spent_coaching(
            session_id=session_id,
            # Every kind of coaching turn, which is what the soft cap is about.
            debrief_seconds=await self._span(session_id, CoachTurn, SparringAttempt),
            sparring_seconds=await self._span(session_id, SparringAttempt),
        )

    async def _span(self, session_id: uuid.UUID, *tables) -> int:
        """Seconds between the first of these and the last, or zero.

        Takes several tables because a coaching engagement is not one of them.
        `debrief_seconds` spans *both* — a re-try is a coaching turn, and a
        session that went straight from the ranked list to sparring would
        otherwise report zero time spent while plainly having spent some. That
        was the first implementation, and the test that caught it is the one
        asserting the debrief contains the sparring rather than sitting beside
        it.

        Zero for a single turn, which is correct rather than a floor: somebody
        who asked one question and left spent no measurable time in the phase,
        and rounding that up to "a turn's worth" would invent engagement.
        """
        edges = [
            (await self._db.execute(
                select(func.min(table.said_at), func.max(table.said_at)).where(
                    table.session_id == session_id
                )
            )).one()
            for table in tables
        ]
        starts = [first for first, _ in edges if first]
        ends = [last for _, last in edges if last]

        return int((max(ends) - min(starts)).total_seconds()) if starts else 0

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
