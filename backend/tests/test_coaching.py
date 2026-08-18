"""A spoken turn, answered.

The assembly #58 exists for: a clip arrives, is heard, reaches a coach that can
only talk about this session, and comes back as words and a voice.

What is tested here is the wiring and the refusals. Whether the coach *reads*
well is measured against a live model in `scripts/coach.py`, where a mock could
not answer the question — and where three faults were found that every test in
this suite was green through.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.coach import COACH, Cite, CoachReply, REDIRECT
from app.agents.context import USER, Said
from app.agents.model import TurnUsage
from app.agents.weakness import Judgement, Weakness
from app.core.errors import FlintroomError
from app.modules.sessions.coaching import CoachService
from app.modules.sessions.debrief import DebriefService
from app.modules.sessions.schemas import EndReason
from app.modules.voice.dictation import Heard

from tests.conftest import ScriptedWeaknessReader
from tests.test_debrief import CountingReader, room_that_happened

ROOM = (
    Said(speaker=USER, text="We grew forty percent last quarter."),
    Said(speaker="cfo", text="Off what base, and at what cost?"),
    Said(speaker=USER, text="We are really pleased with the trajectory."),
)

FOUND = Judgement(
    ordinal=1,
    quote="Off what base, and at what cost?",
    weakness=Weakness.EVASIVE,
    why="You answered with a feeling about the trend, not a base.",
)


class ScriptedDictation:
    """Hears whatever the test says was said, and records what it was given."""

    def __init__(self, text: str = "Why did that one land badly?") -> None:
        self._text = text
        self.heard: list[tuple[bytes, str]] = []

    async def hear(self, clip: bytes, *, media_type: str) -> Heard:
        self.heard.append((clip, media_type))
        return Heard(text=self._text, seconds=3.0)


class ScriptedCoach:
    """Answers from a script, and records the grounds and thread it was shown."""

    def __init__(self, reply: CoachReply | None = None) -> None:
        self._reply = reply or CoachReply(
            text="The CFO wanted a base. You gave a mood.",
            cites=(Cite(kind="line", index=1),),
            usage=TurnUsage(900, 120),
        )
        self.saw_grounds = None
        self.saw_exchange: tuple = ()

    async def reply(self, *, grounds, exchange):
        self.saw_grounds = grounds
        self.saw_exchange = tuple(exchange)
        return self._reply


class ScriptedSpeaker:
    """Two frames, so chunking is visible, and records what it was asked to say."""

    def __init__(self) -> None:
        self.spoke: list[str] = []

    async def speak(self, *, text: str, voice: str | None):
        self.spoke.append(text)
        yield b"\x01\x02"
        yield b"\x03\x04"


async def debriefed(db, engine, sessions, settlement, account, *lines, ended=EndReason.USER_ENDED):
    """A settled room whose ranked list has already been read."""
    session = await room_that_happened(
        db, engine, sessions, settlement, account, *lines, ended=ended
    )
    reader = CountingReader(FOUND)
    await DebriefService(db, reader=reader).weak_answers(session_id=session.id)
    return session


def coaching(db, *, dictation=None, coach=None, speaker=None, reader=None) -> CoachService:
    return CoachService(
        db,
        dictation=dictation or ScriptedDictation(),
        coach=coach or ScriptedCoach(),
        speaker=speaker or ScriptedSpeaker(),
        debrief=DebriefService(db, reader=reader or CountingReader(FOUND)),
    )


async def test_a_spoken_turn_comes_back_as_words_and_a_voice(
    db, engine, sessions, settlement, funded_account
):
    """The tracer: clip in, coach out, both halves of the answer.

    Text as well as audio, and the text is not a convenience. `CLAUDE.md` sets
    the accessibility floor at WCAG 2.2 AA **plus live captions**, as a v1
    requirement rather than a later addition — a voice-only reply is unusable
    for part of the audience, and a client cannot caption audio it was handed as
    bytes.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    speaker = ScriptedSpeaker()

    turn = await coaching(db, speaker=speaker).say(
        session_id=session.id, clip=b"a recording", media_type="audio/wav"
    )

    assert turn.text == "The CFO wanted a base. You gave a mood."
    assert turn.speech == b"\x01\x02\x03\x04"
    assert speaker.spoke == ["The CFO wanted a base. You gave a mood."]


async def test_the_coach_is_handed_the_session_and_nothing_else(
    db, engine, sessions, settlement, funded_account
):
    """The fence's first half, wired.

    §405 names the coach's grounding exactly: the session transcript, ranked
    weak answers, Auditor findings and ingested material. This asserts the coach
    is *given* that and given it whole — the second half, that it cannot claim
    to have seen anything else, is `coach.spoken` and is tested in
    `test_coach.py`.

    A coach handed an empty transcript would pass every other test in this file
    and redirect every turn in production, because there would be nothing valid
    to cite. That failure looks exactly like the fence working.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    coach = ScriptedCoach()

    await coaching(db, coach=coach).say(
        session_id=session.id, clip=b"a recording", media_type="audio/wav"
    )

    assert coach.saw_grounds.transcript == ROOM
    assert [a.ordinal for a in coach.saw_grounds.weak_answers] == [1]


async def test_the_conversation_accumulates_across_turns(
    db, engine, sessions, settlement, funded_account
):
    """§3.5 asks for a conversation, and a conversation remembers.

    Both sides are kept: what the user said and what the coach answered. A
    thread holding only the user's half would let the coach repeat itself
    verbatim and would make a follow-up unanswerable, which is the "static
    dashboard" §3.5 refuses arriving one turn at a time.

    Kept server-side rather than sent by the client, and that is a security
    property rather than a convenience: the thread is model context, so a
    client-supplied history is an injection surface.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    coach = ScriptedCoach()
    service = coaching(db, coach=coach, dictation=ScriptedDictation("And the base?"))

    await service.say(session_id=session.id, clip=b"one", media_type="audio/wav")
    await service.say(session_id=session.id, clip=b"two", media_type="audio/wav")

    assert [(t.who, t.text) for t in coach.saw_exchange] == [
        (USER, "And the base?"),
        (COACH, "The CFO wanted a base. You gave a mood."),
        (USER, "And the base?"),
    ]


async def test_an_ungrounded_turn_is_redirected_and_the_redirect_is_what_is_kept(
    db, engine, sessions, settlement, funded_account
):
    """What the user heard is what the thread must remember.

    The model wanted to review a fresh pitch; the fence replaced it. If the
    thread kept the *intended* text, the next turn would be handed a history in
    which the coach did the thing it refused to do — and would reasonably
    continue doing it. The fence would hold once and then leak into every turn
    after.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    coach = ScriptedCoach(
        CoachReply(text="Your new deck looks strong.", cites=(Cite(kind="line", index=99),))
    )
    service = coaching(db, coach=coach)

    first = await service.say(
        session_id=session.id, clip=b"one", media_type="audio/wav"
    )
    await service.say(session_id=session.id, clip=b"two", media_type="audio/wav")

    assert first.text == REDIRECT
    assert coach.saw_exchange[1].text == REDIRECT


async def test_a_silent_clip_is_not_sent_to_the_coach(
    db, engine, sessions, settlement, funded_account
):
    """Somebody tapped record and said nothing, or the mic was muted.

    Answering an empty turn spends a model call to have the coach respond to
    silence, which reads as a coach talking to itself. Refused with something a
    client can act on — and refused *before* the coach is called, which is the
    assertion, because a version that asked anyway would look identical.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    coach = ScriptedCoach()

    with pytest.raises(FlintroomError) as refused:
        await coaching(db, coach=coach, dictation=ScriptedDictation("")).say(
            session_id=session.id, clip=b"silence", media_type="audio/wav"
        )

    assert refused.value.status_code == 422
    assert coach.saw_grounds is None


async def test_a_room_with_no_debrief_yet_is_read_before_it_is_coached(
    db, engine, sessions, settlement, funded_account
):
    """Somebody who talks before opening the list still gets a grounded coach.

    A phone that jumps straight to the microphone is a real flow, and a coach
    handed no weak answers would be poorer for no reason — the list is the
    ranked half of §405's grounding. So the first coaching turn produces it if
    reading the debrief has not already.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    coach = ScriptedCoach()
    reader = CountingReader(FOUND)

    await coaching(db, coach=coach, reader=reader).say(
        session_id=session.id, clip=b"a recording", media_type="audio/wav"
    )

    assert reader.calls == 1
    assert [a.ordinal for a in coach.saw_grounds.weak_answers] == [1]
