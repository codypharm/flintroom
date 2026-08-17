"""Telling a finished room apart from what it looks like.

`Product.md` §3.5 wants a ranked weak-answer list. `docs/debrief-and-sparring.md`
decision 2 puts that judgement in a reasoning model — reversed there, in the
open, hours after the opposite was decided and built. No rule expressible in code
can see a fluent, specific, confidently *wrong* answer, and catching exactly that
is what §1 means by attacking substance rather than delivery.

**This module is not that judgement.** It is what has to happen before it can be
made honestly.

Three facts about a room are absent from its transcript, and a model handed the
raw text reads all three the same way — as the presenter ducking:

- **The room ended here.** A hanging final question and an evasion are the same
  bytes.
- **This line cut across the previous question.** `Said.disputed`. Once written,
  a disputing line is ordinary panel text following ordinary panel text.
- **The Auditor caught a figure moving.** `Said.chosen_by == "finding"` — the
  only trace that survives, since nothing persists a `Finding`.

So this annotates. Each note is a fact the room held and the text lost, written
plainly enough to sit in a prompt, and **nothing here decides anything**. The
distinction matters: a model that is told *"the cap stopped the room here"* is
better informed, where a model that is told *"this one is weak"* has been
relieved of the job it is there to do.

Verification lives here too, after the model: a weak answer must quote a line
that exists. That is what keeps fabrication non-viable rather than discouraged,
and it is the one property the first, code-first design had that this one is not
allowed to lose.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from app.agents.context import USER, Said
from app.agents.model import TurnUsage
from app.core.logging import get_logger
from app.modules.sessions.schemas import EndReason

log = get_logger(__name__, tag="debrief")


#: The room hit its limit while this question was on the table.
#:
#: Phrased as a fact about the session rather than as an instruction about how to
#: treat it. "Do not blame the presenter for this one" would be a rule, and #43
#: measured what a model does with a rule it is asked to apply — it applies it,
#: everywhere. A model told what happened can work out the rest, and a debrief
#: that says *"the room ran out before you got to this"* is the sentence a person
#: would say anyway.
ENDED_AT_THE_CAP = "The session reached its time limit here, with this question unanswered."

#: This panelist took issue with the previous one's priorities and moved the room
#: onto its own question, before the presenter had answered.
#:
#: The turn shape #54 added, and the debt it created. The architect accepted the
#: audible framing on the ground that the waved-away question survives in the
#: transcript — which it does, illegibly. A disputing line is panel text
#: following panel text, indistinguishable from a panelist who simply had the
#: floor next, so this is the room saying what it knew at the time.
#:
#: Stated as what happened, not as who to excuse. What it implies about the
#: question above is a reading, and reading is the model's job.
CUT_ACROSS = (
    "This panelist interrupted with a different priority; "
    "the question above it was never answered."
)

#: The Auditor caught the answer above this line contradicting something the
#: presenter had already said, and this line is the interruption it caused.
#:
#: The one piece of hard evidence a room produces, and it does not survive one.
#: A `Finding` is read from an utterance, routes the next turn, and is discarded;
#: `auditor.py` keeps every comparison in ordinary code so that a moving figure
#: is arithmetic rather than an impression, and by the debrief that arithmetic is
#: gone.
#:
#: A reasoning model can sometimes notice the same contradiction unaided.
#: *Sometimes* is the objection: this is the product's sharpest claim about
#: itself, and it should not be re-derived by inspection when the room already
#: proved it deterministically.
AUDITOR_CAUGHT = (
    "A figure in the answer above this line contradicted one the presenter "
    "gave earlier; that is what prompted this interruption."
)


@dataclass(frozen=True)
class Annotated:
    """One line of the room, plus what the room knew that the line does not say.

    Carries its `ordinal` rather than relying on position, because this is what
    the model is shown and what it must quote back. A weak answer arrives naming
    an ordinal, and that ordinal has to mean the same thing on both sides of the
    call.
    """

    ordinal: int
    said: Said
    notes: tuple[str, ...] = field(default_factory=tuple)


def annotate(
    transcript: Sequence[Said], *, ended: EndReason
) -> tuple[Annotated, ...]:
    """The room as the model should see it: the text, plus what it cannot show.

    `ended` is required rather than defaulted. There is no safe value to assume —
    a room stopped by the cap and a room stopped by ninety seconds of silence
    produce an identical final line, and a default would quietly pick one of
    those readings for every caller that did not think about it.
    """
    ending = _hanging_question(transcript)

    return tuple(
        Annotated(
            ordinal=ordinal,
            said=line,
            notes=_notes_on(ordinal, line, ending=ending, ended=ended),
        )
        for ordinal, line in enumerate(transcript)
    )


def _notes_on(
    ordinal: int, line: Said, *, ending: int | None, ended: EndReason
) -> tuple[str, ...]:
    """What the room knew about this line and the transcript does not record.

    A tuple because one line can carry more than one — the room can perfectly
    well run out of time on a question that was itself an interruption.
    """
    notes: list[str] = []

    if line.disputed:
        notes.append(CUT_ACROSS)
    if line.chosen_by == "finding":
        notes.append(AUDITOR_CAUGHT)
    if ordinal == ending and _ran_out(ended):
        notes.append(ENDED_AT_THE_CAP)

    return tuple(notes)


def _ran_out(ended: EndReason) -> bool:
    """Whether the room stopped for a reason that was not the presenter's silence.

    `IDLE_TIMEOUT` is the exception and gets no note: it means no user speech
    while the panel awaited an answer, for ninety seconds. Silence that long in
    front of a question is not the clock running out, it is an answer.
    """
    return ended is not EndReason.IDLE_TIMEOUT


def _hanging_question(transcript: Sequence[Said]) -> int | None:
    """The question the room stopped on, or `None` if it did not stop on one.

    Strictly the last line, and only if the panel said it. The looser reading —
    the last *panel* line anywhere in the transcript — was written first and is
    wrong: a room whose final exchange was a question and an answer would have
    that question marked as the one time ran out on, while the answer to it sits
    directly underneath.

    Which is worse than an omission. A note is a fact handed to a model that has
    no way to check it, so a false one is believed, and this particular false one
    would tell somebody the clock robbed them of a question they answered.
    """
    if not transcript or transcript[-1].speaker == USER:
        return None
    return len(transcript) - 1


class Weakness(Enum):
    """The vocabulary a weak answer may be filed under.

    Fixed, and the model must choose from it. Free-text categories would be
    unusable downstream — the prep sheet groups by this, sparring branches on it,
    and #55 will count it — and a vocabulary that drifts between runs cannot be
    counted at all.

    Six, deliberately few. Every one of them is a sentence a person would
    recognise about their own answer; a taxonomy finer than that is a taxonomy
    nobody can tell apart, including the model choosing from it.

    No `PRESSED`. A panelist asking twice is *evidence* rather than a kind of
    weakness, it is plainly visible in the transcript without help, and the
    answer it points at is already either evasive or unsupported. It survives in
    the `why`, where it reads better anyway: "the CFO had to ask twice."
    """

    #: Nobody answered it. The presenter moved on, or said nothing.
    UNANSWERED = "unanswered"

    #: A colleague took issue with its priority and moved the room on, before
    #: the presenter had the floor. Not their fault; still their question.
    DISMISSED = "dismissed"

    #: The room ended on it. The clock, not the presenter.
    NOT_REACHED = "not_reached"

    #: A figure conflicts with another figure the presenter gave — in an earlier
    #: answer, or inside the same one.
    #:
    #: Widened after measurement. It first read "a figure moved", meaning the
    #: Auditor's catch, and a reader handed *"twelve hundred to acquire, a
    #: hundred and eighty a month, so payback is four months"* filed it here
    #: anyway. That was the right call and the definition was too narrow:
    #: arithmetic that does not work is two of the presenter's own figures
    #: disagreeing, which is the Auditor's shape reached by reading rather than
    #: by comparison.
    CONTRADICTED = "contradicted"

    #: Asserted with nothing behind it — no figure, no source, no mechanism.
    UNSUPPORTED = "unsupported"

    #: Answered, fluently, but not the question that was asked.
    EVASIVE = "evasive"


@dataclass(frozen=True)
class Judgement:
    """What the model says about one question, before anything is believed.

    Separate from `WeakAnswer` on purpose. This is a claim; a `WeakAnswer` is a
    claim that survived checking, and collapsing the two would leave nothing in
    the type system to distinguish what a model said from what is true.
    """

    #: Which line it is judging. Checked against `quote`, never trusted alone.
    ordinal: int

    #: The words it read there. The evidence that it read there at all.
    quote: str

    weakness: Weakness

    #: The sentence the coach says. Prose, because this is the part a person
    #: reads, and a category cannot tell somebody what was thin about an answer.
    why: str


@dataclass(frozen=True)
class WeakAnswer:
    """One question the room did not get a good enough answer to.

    Every field but `weakness` and `why` is read from the transcript rather than
    taken from the model. It cannot misquote what it is not asked to supply, and
    the prep sheet showing a user their own words has to show *their* words.
    """

    ordinal: int
    question: str
    asked_by: str

    #: What they said in reply, or `None` when they said nothing.
    answer: str | None

    weakness: Weakness
    why: str


def verified(
    judged: Sequence[Judgement], transcript: Sequence[Said]
) -> tuple[WeakAnswer, ...]:
    """The judgements that survive being checked against the room.

    Handing the verdict to a model buys the ability to see a fluent, confidently
    wrong answer, which no rule in code can. What it must not buy is the ability
    to invent one: a debrief that tells somebody they fumbled a question nobody
    asked is worse than one that misses a real fumble, because it destroys the
    premise that the product was listening.

    So a judgement must name a line *and* quote it, and the two must agree. The
    ordinal alone would be cheap — any integer in range looks plausible, and a
    model that picked one without reading would pass. The quote is what makes
    reading the only way through.

    Dropped rather than raised. A model that got one of eight wrong has still
    produced seven useful ones, and a debrief that refuses to open because a
    single quote drifted is worse for the user than a debrief with seven items.
    The drop is logged, because a quiet one is how a prompt regression becomes a
    debrief that silently gets shorter.
    """
    kept: list[WeakAnswer] = []

    for judgement in judged:
        if not _quotes_the_room(judgement, transcript):
            # Never the quote itself: it is transcript text either way — the
            # model's copy of it, or its invention about a room — and
            # `CLAUDE.md` forbids transcript text in logs without exception.
            log.warning(
                "weak_answer_unverified",
                ordinal=judgement.ordinal,
                weakness=judgement.weakness.value,
            )
            continue

        line = transcript[judgement.ordinal]
        kept.append(
            WeakAnswer(
                ordinal=judgement.ordinal,
                question=line.text,
                asked_by=line.speaker,
                answer=_answer_to(transcript, judgement.ordinal),
                weakness=judgement.weakness,
                why=judgement.why,
            )
        )

    return tuple(kept)


def _quotes_the_room(judgement: Judgement, transcript: Sequence[Said]) -> bool:
    """Whether the quoted words are really at the ordinal named.

    Containment rather than equality, and normalised for case and whitespace. A
    model quoting the clause it is judging out of a three-sentence question is
    doing the right thing; failing it for that would train the prompt toward
    copying whole lines, which makes the check pass without making it stronger.
    """
    if not 0 <= judgement.ordinal < len(transcript):
        return False
    return _plainly(judgement.quote) in _plainly(transcript[judgement.ordinal].text)


def _plainly(text: str) -> str:
    """Case- and whitespace-insensitive, so a reflowed quote still matches."""
    return " ".join(text.lower().split())


def _answer_to(transcript: Sequence[Said], ordinal: int) -> str | None:
    """What the presenter said in reply to the question at `ordinal`, if anything.

    Everything up to the next panel line, because a person answering a hard
    question pauses, and a pause is two transcript lines rather than one.
    """
    spoken: list[str] = []

    for line in transcript[ordinal + 1 :]:
        if line.speaker != USER:
            break
        spoken.append(line.text)

    return " ".join(spoken) if spoken else None


@dataclass(frozen=True)
class WeaknessReading:
    """What a reader said about a room, and what saying it cost.

    Text and price arrive together, the pairing `ModelReply` already makes. The
    debrief is unmetered but not free, and §4.3 names the unmetered phases as the
    model's largest uncontrolled exposure — a seam that returned only judgements
    would leave the one call this phase makes invisible to the only table that
    reconciles against an invoice.
    """

    judged: tuple[Judgement, ...] = ()
    usage: TurnUsage = TurnUsage()


@dataclass(frozen=True)
class Ranked:
    """The room's weak answers, verified, and what reading them cost."""

    answers: tuple[WeakAnswer, ...] = ()
    usage: TurnUsage = TurnUsage()


#: Checkable at runtime for the reason `TranscriptStore` and `ClaimReader` are:
#: there is no base class to inherit and no type checker in the suite, so an
#: adapter that drifted off this seam would stay green everywhere and surface as
#: a debrief that never finds anything — which reads exactly like a good room.
@runtime_checkable
class WeaknessReader(Protocol):
    """Whatever reads a finished room and says what went badly in it."""

    async def rank(self, *, room: Sequence[Annotated]) -> WeaknessReading:
        """Judge the room. One call, offline, after everything.

        Takes `Annotated` rather than `Said`, and that is the seam's whole point:
        a reader handed the raw transcript cannot tell a question the clock took
        away from one the presenter ducked, and will say so confidently.

        Returns `Judgement`s — claims, not conclusions. Every one is checked
        against the transcript before anything downstream believes it.

        **May raise, and the caller must survive it.** Unlike a turn, nothing is
        live here, so a failure costs a retry rather than silence in a room.
        """
        ...


async def weak_answers(
    transcript: Sequence[Said], *, ended: EndReason, reader: WeaknessReader
) -> Ranked:
    """What went badly in this room, ranked, from a finished transcript.

    Three steps and each belongs where it is. Code annotates, because the facts
    involved are not in the text and no amount of reading recovers them. The
    model judges, because that is reading and code cannot do it. Code verifies,
    because a claim about a room can be checked against the room.

    The order the reader returns is kept. It is the ranking — that is what was
    asked for — and re-sorting by category here would overrule a judgement made
    with the whole room in view using a table written before any room existed.
    """
    reading = await reader.rank(room=annotate(transcript, ended=ended))

    return Ranked(
        answers=verified(reading.judged, transcript), usage=reading.usage
    )


def to_judgements(reported: Any) -> tuple[Judgement, ...]:
    """Typed judgements, in the order the model put them in.

    **The order is the ranking** and is preserved exactly. It was decided with
    the whole room in view by the only thing in the pipeline that read it, and
    nothing here is better placed to second-guess it.

    Malformed entries are dropped rather than raised on, matching
    `to_claims`: one bad item out of five should cost that item, not the debrief.
    A room that produced four usable findings and one unparseable one is still a
    debrief worth opening.
    """
    if not isinstance(reported, dict) or not isinstance(reported.get("weak"), list):
        return ()

    judged: list[Judgement] = []

    for entry in reported["weak"]:
        judgement = _judgement(entry)
        if judgement is None:
            log.warning("weak_answer_malformed")
            continue
        judged.append(judgement)

    return tuple(judged)


def _judgement(entry: Any) -> Judgement | None:
    """One entry, or `None` if it is not one.

    Every field is checked for the type it has to be. A `quote` that arrived as
    a list, or an `ordinal` as a string, would otherwise reach
    `weakness.verified` and fail there — later, further from the cause, and
    logged as an unverified quote rather than as a malformed reply.
    """
    if not isinstance(entry, dict):
        return None

    ordinal, quote = entry.get("ordinal"), entry.get("quote")
    weakness, why = entry.get("weakness"), entry.get("why")

    # `bool` is an `int` in Python, and `True` as an ordinal would index line
    # one. Cheap to exclude, silent and baffling if it ever happened.
    if not isinstance(ordinal, int) or isinstance(ordinal, bool):
        return None
    if not isinstance(quote, str) or not isinstance(why, str):
        return None
    if not quote.strip() or not why.strip():
        return None

    try:
        named = Weakness(weakness)
    except ValueError:
        # A category outside the fixed vocabulary. Dropped rather than coerced
        # to a default: the prep sheet groups on this and #55 will count it, so
        # an invented category quietly filed under "unsupported" is worse than
        # one finding fewer.
        return None

    return Judgement(ordinal=ordinal, quote=quote, weakness=named, why=why)


def render(room: Sequence[Annotated]) -> str:
    """The transcript, one numbered line each, notes indented beneath.

    Numbered because the reply names ordinals, and a model asked for a line
    number it was never shown is being asked to count. Notes below their line
    rather than inline, so they read as a fact *about* it rather than as part of
    what was said — a note spliced into a panelist's sentence would come back
    quoted as if somebody had spoken it, and pass the quote check.
    """
    lines: list[str] = []

    for line in room:
        who = "PRESENTER" if line.said.speaker == USER else line.said.speaker
        lines.append(f"[{line.ordinal}] {who}: {line.said.text}")
        lines.extend(f"      ({note})" for note in line.notes)

    return "\n".join(lines)


#: Shared with the Claude reader, because it is the job rather than the vendor.
#:
#: Asks for a reading and never for a rule to be applied. #43 measured what
#: happens to a rule handed to a model — asked whether the presenter had dodged,
#: it said yes on 4 of 4 dodges *and* 4 of 4 genuine answers. What replaces the
#: rule is a forced ranking, a required quote, and `weakness.verified` checking
#: that quote afterwards.
INSTRUCTION = """\
You are reviewing a rehearsal session. A panel of experts interrogated a \
presenter, and the full transcript follows, one numbered line at a time.

Some lines carry a note in parentheses. Those are facts about the session that \
the transcript itself cannot show. Take them as true.

Identify the answers the presenter handled worst, and list them worst first. \
Return at most six. Fewer is correct when the session was short or went well; \
an empty list is the right answer for a session with nothing wrong in it.

Judge the substance, not the delivery. The most important thing you can catch \
is an answer that sounds confident and specific but does not hold up — a figure \
that cannot be right, arithmetic that does not work, a mechanism that does not \
follow, a claim with nothing behind it. Nothing else in this system can see \
those.

For each one:
- `ordinal` is the numbered line of the QUESTION, never the answer.
- `quote` must be words copied exactly from that line.
- `why` speaks to the presenter, in one or two sentences, about what was \
missing from what they actually said. Never generic advice.

Do not blame the presenter for a question a note says they were never given the \
chance to answer. It still belongs on the list — they will face it again — but \
say what actually happened.\
"""
