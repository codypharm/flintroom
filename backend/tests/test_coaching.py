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

from app.agents.archetypes import LIBRARY
from app.agents.voices import CASTABLE
from app.modules.sessions.coaching import COACH_VOICE
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.coach import COACH, Cite, CoachReply, REDIRECT
from app.agents.context import USER, Said
from app.agents.model import TurnUsage
from app.agents.weakness import Judgement, Weakness
from app.core.errors import FlintroomError
from app.modules.sessions.coaching import CoachService
from app.modules.sessions.debrief import DebriefService
from app.modules.sessions.models import SparringAttempt
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


class SparringCoach(ScriptedCoach):
    """Records the question and the run of attempts it was shown."""

    def __init__(self, reply: CoachReply | None = None) -> None:
        super().__init__(reply)
        self.saw_weak = None
        self.saw_attempts: tuple = ()

    async def spar(self, *, grounds, weak, attempts):
        self.saw_grounds = grounds
        self.saw_weak = weak
        self.saw_attempts = tuple(attempts)
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


async def test_a_retry_is_shown_every_go_so_far_and_the_answer_that_failed(
    db, engine, sessions, settlement, funded_account
):
    """The loop cannot say what changed without both sides of the change.

    §3.5 says "repeatedly", so the coach needs the whole run rather than the
    latest string: *"you are further from it than you were two tries ago"* is
    true, useful, and unsayable by something holding one attempt.

    The original answer goes too. Without it the first retry has nothing to be
    compared against, and the coach would be reduced to describing an answer
    rather than a difference — which is the static reading §3.5 refuses.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    coach = SparringCoach()
    service = coaching(db, coach=coach, dictation=ScriptedDictation("Two million ARR."))

    await service.spar(
        session_id=session.id, weak_rank=0, clip=b"one", media_type="audio/wav"
    )
    service._dictation = ScriptedDictation("Two million, up from one point four.")
    await service.spar(
        session_id=session.id, weak_rank=0, clip=b"two", media_type="audio/wav"
    )

    assert coach.saw_attempts == (
        "Two million ARR.",
        "Two million, up from one point four.",
    )
    assert coach.saw_weak.answer == "We are really pleased with the trajectory."


async def test_only_a_question_the_room_actually_asked_can_be_sparred(
    db, engine, sessions, settlement, funded_account
):
    """The anchor, and it is a fence rather than a lookup.

    A re-answer is fresh speech about the session — the one shape *"spar me on
    this instead"* would use to introduce a new pitch. Because the question is a
    stored rank rather than something the caller describes, there is no argument
    in which a different subject could be named.

    Refused before the clip is heard, which is the assertion: transcribing first
    would pay a vendor to produce a string with nowhere to put it.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    dictation = ScriptedDictation()

    with pytest.raises(FlintroomError) as refused:
        await coaching(db, dictation=dictation).spar(
            session_id=session.id, weak_rank=7, clip=b"one", media_type="audio/wav"
        )

    assert refused.value.status_code == 404
    assert dictation.heard == []


async def test_what_the_user_heard_is_what_the_attempt_records(
    db, engine, sessions, settlement, funded_account
):
    """A redirected retry must not be remembered as the answer it wanted to give.

    Same reasoning as the coaching thread, and it bites harder here: #55 reads
    these rows to decide how hard the next room should be. An attempt stored
    with the model's intended text would tell a future calibration that a
    presenter was coached through something they were actually redirected away
    from.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    coach = SparringCoach(
        CoachReply(text="Your new deck is strong.", cites=(Cite(kind="line", index=99),))
    )

    turn = await coaching(db, coach=coach).spar(
        session_id=session.id, weak_rank=0, clip=b"one", media_type="audio/wav"
    )

    kept = (
        await db.execute(
            select(SparringAttempt).where(SparringAttempt.session_id == session.id)
        )
    ).scalars().all()

    assert turn.text == REDIRECT
    assert [row.reply for row in kept] == [REDIRECT]


async def test_attempts_come_back_in_the_order_they_were_made(
    db, engine, sessions, settlement, funded_account
):
    """Order is the comparison, and the comparison is the whole feature.

    Attempts read out of order hand the coach the run backwards, so it reports
    somebody regressing when they improved — the most damaging thing a re-try
    loop can say, and said with no error anywhere.

    The planner is pushed off the primary key for the reason recorded in
    `test_debrief.py`: the key is (session_id, weak_rank, attempt), so an index
    scan returns them sorted whatever the ORDER BY says, and the clause is right
    and unfalsifiable at the same time. Verified with EXPLAIN when that lesson
    was first learned; the SET LOCAL must come *after* the commit, because it
    dies with the transaction that set it.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)

    for attempt, said in ((2, "third go"), (0, "first go"), (1, "second go")):
        db.add(
            SparringAttempt(
                session_id=session.id,
                weak_rank=0,
                attempt=attempt,
                said=said,
                reply="noted",
            )
        )
    await db.commit()

    await db.execute(text("SET LOCAL enable_indexscan = off"))
    await db.execute(text("SET LOCAL enable_bitmapscan = off"))

    coach = SparringCoach()
    await coaching(db, coach=coach, dictation=ScriptedDictation("fourth go")).spar(
        session_id=session.id, weak_rank=0, clip=b"x", media_type="audio/wav"
    )

    assert coach.saw_attempts == ("first go", "second go", "third go", "fourth go")


# --- The coach opening the debrief -----------------------------------------
#
# Reported from a device: "there is no verdict from the session". The room ends
# with two voices interrogating you and the debrief arrives as a page of text
# and a microphone button — nothing greets you, and nothing was ever going to,
# because every coach turn until now needed a clip to answer.
#
# `design-guide/coaching_debrief/` reached for this too: a "Voice Coach Audio
# Review" player at the top of the sheet. What that mockup ALSO has is a B+ in
# a circle over "Solid Delivery, Minor Gaps", which is the delivery scorer §1
# exists to refuse. The opening is a verdict in every sense that helps somebody
# and in none of the senses that scores them.


class OpeningCoach(ScriptedCoach):
    """Answers an opening from a script, and records what it was shown."""

    def __init__(self, reply: CoachReply | None = None) -> None:
        super().__init__(reply)
        self.opened = 0

    async def open(self, *, grounds):
        self.saw_grounds = grounds
        self.opened += 1
        return self._reply


async def test_the_coach_speaks_first_when_the_debrief_opens(
    db, engine, sessions, settlement, funded_account
):
    """The tracer. No clip, and a reply anyway.

    Every coach turn before this one needed something said to it. This is the
    turn that makes the debrief a conversation somebody joins rather than a
    form they fill in — and it is why the autoplay the client just gained lands
    on turn one instead of turn two.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    speaker = ScriptedSpeaker()

    opening = await coaching(db, coach=OpeningCoach(), speaker=speaker).open(
        session_id=session.id
    )

    assert opening is not None
    assert opening.text == "The CFO wanted a base. You gave a mood."
    assert opening.speech == b"\x01\x02\x03\x04"


async def test_the_opening_is_written_once_and_then_only_recalled(
    db, engine, sessions, settlement, funded_account
):
    """The debrief read is idempotent by design and this must not break it.

    `read_debrief`'s own docstring: the first open computes and stores, every
    open after hands back what was stored, *"because backgrounding and resuming
    re-fetches"*. A second model call here would also reword the greeting, so
    the same room would be introduced differently every time somebody glanced
    at their phone.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    coach = OpeningCoach()
    service = coaching(db, coach=coach)

    first = await service.open(session_id=session.id)
    again = await service.open(session_id=session.id)

    assert coach.opened == 1
    assert again is not None and again.text == first.text


async def test_coming_back_to_a_debrief_is_not_being_greeted_again(
    db, engine, sessions, settlement, funded_account
):
    """The money decision, enforced in code rather than remembered.

    The coach runs on the expressive speaker, measured in `docs/voice-cost.md`
    at twice Flash — roughly $0.0002 a character, so a spoken opening costs
    about what a full minute of live interrogation does. Backgrounding the app
    ten times would spend ten rooms' worth on an unmetered phase.

    So the audio is produced once, for the arrival it belongs to. The text
    survives because it is stored; the voice does not, and asking for it again
    is a deliberate request with its own endpoint.

    It is also the rule this product already made once. `Silence.asked()`: a
    room that asks twice has stopped being a room and become a smoke alarm.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    speaker = ScriptedSpeaker()
    service = coaching(db, coach=OpeningCoach(), speaker=speaker)

    await service.open(session_id=session.id)
    again = await service.open(session_id=session.id)

    assert again is not None and again.text
    assert again.speech == b""
    assert len(speaker.spoke) == 1


async def test_the_opening_is_the_first_thing_the_next_turn_can_see(
    db, engine, sessions, settlement, funded_account
):
    """Kept in the thread, not held beside it.

    A coach that greeted somebody and then could not see it had done so would
    open the conversation twice, and the second turn would answer a question
    the user is replying to as though it had never been asked.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    said = ScriptedCoach()
    service = coaching(db, coach=OpeningCoach())

    await service.open(session_id=session.id)
    await coaching(db, coach=said).say(
        session_id=session.id, clip=b"a recording", media_type="audio/wav"
    )

    assert [turn.who for turn in said.saw_exchange] == [COACH, USER]


async def test_the_opening_sees_the_session_and_nothing_else(
    db, engine, sessions, settlement, funded_account
):
    """The same fence as every other turn, and for the same reason.

    §405 bounds the coach to the transcript, the ranked weak answers, the
    Auditor's findings and the ingested material. An opening is the one turn
    with no user speech to anchor it, which makes it the one most able to
    wander — so it is handed `Grounds` exactly as `reply` is, and its citations
    are checked by the same `spoken`.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    coach = OpeningCoach()

    await coaching(db, coach=coach).open(session_id=session.id)

    assert coach.saw_grounds is not None
    assert coach.saw_grounds.transcript == ROOM
    assert [answer.question for answer in coach.saw_grounds.weak_answers] == [
        "Off what base, and at what cost?"
    ]


async def test_an_opening_that_claims_something_it_cannot_cite_is_redirected(
    db, engine, sessions, settlement, funded_account
):
    """`spoken` is the half of the fence that holds when the prompt is jailbroken.

    Nothing about this turn is special enough to skip it. An opening with no
    user speech in front of it is the turn most likely to reach for a general
    observation about pitching, which is the competitor product the wedge
    refuses.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    ungrounded = OpeningCoach(
        CoachReply(text="Great decks always open with a story.", cites=(), usage=TurnUsage(10, 10))
    )

    opening = await coaching(db, coach=ungrounded).open(session_id=session.id)

    assert opening is not None and opening.text == REDIRECT


async def test_nobody_is_greeted_into_the_middle_of_a_conversation(
    db, engine, sessions, settlement, funded_account
):
    """A client that goes straight to the microphone gets no opening at all.

    Reachable: `say` runs `_grounds` through `DebriefService` precisely so that
    a phone jumping to the mic without reading the list first is still coached
    properly. That path leaves a thread whose first line is the user's, and
    introducing the room after they have already asked something would read as
    the coach not having been listening.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    await coaching(db).say(
        session_id=session.id, clip=b"a recording", media_type="audio/wav"
    )

    assert await coaching(db, coach=OpeningCoach()).open(session_id=session.id) is None


def test_the_coach_is_cast_rather_than_left_to_the_house_voice():
    """The coach was mute in every debrief, and nothing said so.

    `_voice` asked for synthesis with `voice=None`, which `ElevenLabsSpeaker`
    resolves through `self._default_voice_id` — and that comes from
    `ELEVENLABS_DEFAULT_VOICE_ID`, unset in a working `.env`. So the fallback
    fell back to nothing: the adapter logged `voice_uncast`, refused, and the
    endpoint answered 502.

    The failure was invisible because the debrief READ still succeeded and
    returned the opening with `speech: ""` — text with silence attached, rather
    than an error anybody could see. Verified against the running server on
    2026-08-20: five settled rooms, every one of them a silent debrief.

    Casting the coach explicitly is the fix rather than setting the variable.
    A house voice is a deployment concern that fails quietly; a cast one is
    configuration in a file, tested, and the same mechanism every panelist
    already uses.
    """
    assert COACH_VOICE in CASTABLE


def test_the_coach_shares_a_voice_and_that_is_a_known_cost():
    """**I asserted the opposite first, and the suite proved me wrong.**

    The claim was that WARM is the one voice no archetype is cast in. It is not:
    all eight voices are cast to the eight shipped archetypes, so a ninth
    speaker cannot avoid a collision. `voices.py` says why the roster is that
    size — *"Eight, matching the eight shipped archetypes, because casting them
    established the vocabulary. Adding a ninth means adding a vendor voice
    behind it in every adapter."*

    So the coach shares with the Customer Advocate, and the cost is real: in a
    room that seated the Advocate, the person helping afterwards sounds like one
    of the people who just pressed them. WARM is still the best of the eight for
    the job — *"open and direct, the easiest of them to listen to"* — and the
    Advocate is among the less commonly seated.

    **The fix is a ninth voice, and it is the architect's to authorise**: it
    needs a real vendor identifier added to `ELEVENLABS_VOICES`, which cannot be
    invented here without calling the provider. Recorded as a test rather than a
    comment so the collision is a stated position rather than an oversight.
    """
    seated = {archetype.voice for archetype in LIBRARY}

    assert COACH_VOICE in seated, "a ninth voice landed — give the coach its own"
