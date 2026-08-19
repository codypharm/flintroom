"""What the room found, read back off a finished transcript.

`Product.md` §3.5 wants a *ranked weak-answer list* — "which questions went
unanswered, which claims lacked support, where the argument contradicted
itself". `docs/debrief-and-sparring.md` decision 2 settles who decides, and was
reversed hours after it was first taken:

    **The model judges; code supplies what the transcript does not carry.**

A reasoning model reads the room and decides what was weak, because no rule
expressible in code can see a fluent, specific, confidently *wrong* answer — and
catching exactly that is what §1 means by attacking substance rather than
delivery. The debrief is also the only phase in the product that can afford a
long think: it runs once, offline, after the room, against no clock at all.

What code keeps is the part that is not judgement. **Three facts are not in the
transcript**, and a model given the raw text reads all three as a dodge — not
because it is careless, but because there is nothing there to read otherwise.
These tests are about putting those facts in front of it.
"""

from __future__ import annotations

import pytest

from app.agents.context import USER, Said
from app.agents.weakness import (
    AUDITOR_CAUGHT,
    CUT_ACROSS,
    ENDED_AT_THE_CAP,
    OPENED_THE_ROOM,
    Judgement,
    WeakAnswer,
    Weakness,
    WeaknessReading,
    annotate,
    verified,
    weak_answers,
)
from app.agents.model import TurnUsage
from app.modules.sessions.schemas import EndReason


def notes_on(room, *, ended) -> dict[int, tuple[str, ...]]:
    """Every line that carries a note, by ordinal, except the opening one.

    #79 gave every room an opening statement, and every fixture below begins
    with one — so `OPENED_THE_ROOM` would appear in every expectation here
    while saying nothing about the fact each test was actually written for.
    It is asserted directly, in its own tests further down.

    The filter does not weaken the guard in
    `test_an_ordinary_room_carries_no_notes_at_all`: an implementation that
    returned every note on every line would still show the other three.
    """
    kept = {
        line.ordinal: tuple(note for note in line.notes if note != OPENED_THE_ROOM)
        for line in annotate(room, ended=ended)
    }
    return {ordinal: notes for ordinal, notes in kept.items() if notes}


def test_the_room_running_out_of_time_is_said_out_loud():
    """A hanging final question and an evasion are the same bytes.

    The clearest case of a fact the text cannot carry. Nothing distinguishes a
    question the presenter refused to answer from one the twelve-minute cap took
    away from them — same speaker, same position, same silence after it.

    A model handed the raw transcript will call it a dodge, and be right to, on
    the evidence it was given. Telling somebody they ducked a question they were
    never allowed to answer is the accusation #56 exists to prevent, and under
    Open Risk #1 it is close to the worst thing this product can say.

    So the note is not the model being second-guessed. It is the model being told
    something only the room knew.
    """
    room = (
        Said(speaker=USER, text="Revenue tripled last year."),
        Said(speaker="cfo", text="Off what base, and what did it cost to get there?"),
    )

    assert notes_on(room, ended=EndReason.SESSION_CAP) == {1: (ENDED_AT_THE_CAP,)}


def test_a_colleague_taking_the_room_away_is_said_out_loud():
    """The obligation #54 created, paid in the only currency that works.

    The architect chose the audible framing of inter-panelist disagreement
    knowing it is mildly dismissive by nature — measured, a CFO says
    *"Sponsorship matters less than the operational debt of that rebuild"* and
    moves the room onto its own question. That was accepted on an explicitly
    architectural ground: the waved-away question survives in the transcript, and
    something downstream reads it back.

    But it does not survive *legibly*. Once written, a disputing line is panel
    text following panel text, exactly like a panelist who simply had the floor
    next. The room knew the difference at the moment it happened and the record
    does not, so this is where the room says it.

    Note goes on the *disputing* line rather than on the question it displaced.
    That is where the fact belongs — this line did the cutting — and it leaves
    the model to work out what it implies about the line above, which is the
    reading it is there to do.
    """
    room = (
        Said(speaker=USER, text="Sponsorship is locked in for the year."),
        Said(speaker="champion", text="Who inside the company will sponsor this?"),
        Said(
            speaker="cfo",
            text="The operational debt matters more. What does it cost to carry?",
            disputed=True,
        ),
        Said(speaker=USER, text="About two engineers full time."),
    )

    assert notes_on(room, ended=EndReason.USER_ENDED) == {2: (CUT_ACROSS,)}


def test_the_auditors_catch_is_said_out_loud():
    """The one piece of hard evidence in the room, and it does not survive.

    A `Finding` is read from one utterance, routes the next turn, and is
    discarded — `auditor.py` keeps every comparison in ordinary code precisely so
    that a moving figure is arithmetic rather than an impression. By the time a
    debrief opens, that arithmetic is gone and only `chosen_by` remembers it
    happened.

    A reasoning model could sometimes spot the same contradiction unaided, and
    that is not good enough. Sometimes is exactly the word: the Auditor is
    deterministic and this is the product's sharpest claim about itself, so the
    debrief should not be re-deriving by inspection something the room already
    proved.

    Note goes on the *interrupting* line, matching CUT_ACROSS. The contradiction
    is in the answer above it, and the panel line says so in words the user
    actually heard (#45) — so the model is being pointed at evidence already in
    front of it rather than handed a second version of it.
    """
    room = (
        Said(speaker=USER, text="Margin is seventy percent."),
        Said(speaker="cfo", text="Across which lines?"),
        Said(speaker=USER, text="Blended it is about sixty-one."),
        Said(
            speaker="cfo",
            text="You said seventy a moment ago. Which is it?",
            chosen_by="finding",
        ),
        Said(speaker=USER, text="Sixty-one is the right number."),
    )

    assert notes_on(room, ended=EndReason.USER_ENDED) == {3: (AUDITOR_CAUGHT,)}


def test_an_ordinary_room_carries_no_notes_at_all():
    """Silence is the default, and it has to be, or the notes mean nothing.

    Every note is a fact the model cannot verify and will therefore believe. A
    room where nothing unusual happened must produce none — otherwise the
    annotations stop being evidence and become decoration, and the one that
    matters gets read at the same weight as the ones that do not.

    This is also the guard against the cheapest possible wrong implementation.
    Returning every note on every line would satisfy all three tests above.
    """
    room = (
        Said(speaker=USER, text="We grew forty percent last quarter."),
        Said(speaker="cfo", text="Off what base?"),
        Said(speaker=USER, text="Two million ARR at the start of the year."),
    )

    assert notes_on(room, ended=EndReason.USER_ENDED) == {}


def test_a_judgement_that_quotes_something_nobody_said_is_dropped():
    """The property the code-first design had that this one may not lose.

    Handing the verdict to a model buys the ability to see a fluent, wrong
    answer. What it must not buy is the ability to invent one — a debrief that
    tells somebody they fumbled a question nobody asked is worse than a debrief
    that misses a real fumble, because it destroys the premise that the product
    was listening.

    So the model names an ordinal *and* quotes the line, and code checks the two
    agree. The ordinal alone would be cheap: any integer in range looks
    plausible, and a model that picked one without reading would be
    indistinguishable from one that read carefully. The quote is what makes
    reading the only way to pass.

    Both judgements here name a real ordinal. Only one of them quotes what is
    actually at it.
    """
    room = (
        Said(speaker=USER, text="Margin is seventy percent."),
        Said(speaker="cfo", text="Off what base?"),
        Said(speaker=USER, text="It has been strong all year."),
    )
    judged = (
        Judgement(
            ordinal=1,
            quote="Off what base?",
            weakness=Weakness.EVASIVE,
            why="No base was ever given.",
        ),
        Judgement(
            ordinal=1,
            quote="What is your burn rate?",
            weakness=Weakness.UNSUPPORTED,
            why="Nobody asked this.",
        ),
    )

    assert [answer.why for answer in verified(judged, room)] == [
        "No base was ever given."
    ]


class Reading:
    """A reader that records the room it was shown and answers from a script."""

    def __init__(self, *judged: Judgement) -> None:
        self._judged = judged
        self.saw: tuple = ()

    async def rank(self, *, room):
        self.saw = tuple(room)
        return WeaknessReading(judged=self._judged, usage=TurnUsage(1200, 300))


@pytest.mark.asyncio
async def test_the_reader_is_shown_the_room_with_its_notes_and_its_answer_is_checked():
    """The tracer bullet: annotate, read, verify, and carry what it cost.

    Asserted on what the reader was *given* as well as what came back, because
    the annotations are the whole reason this is not simply a prompt over a
    transcript. A version that computed the notes correctly and then handed the
    model the raw text would pass every annotation test in this file and be
    exactly as unfair as having no notes at all.

    `usage` travels because the debrief is unmetered, not free. §4.3 names the
    unmetered phases as the model's largest uncontrolled exposure, and a call
    whose cost is not returned from the seam that made it cannot be counted by
    anything outside.
    """
    room = (
        Said(speaker=USER, text="Sponsorship is locked in."),
        Said(speaker="champion", text="Who inside the company will sponsor this?"),
        Said(speaker="cfo", text="The debt matters more. What does it cost?", disputed=True),
        Said(speaker=USER, text="About two engineers full time."),
    )
    reader = Reading(
        Judgement(
            ordinal=1,
            quote="Who inside the company will sponsor this?",
            weakness=Weakness.DISMISSED,
            why="A colleague redirected the room before you answered.",
        )
    )

    ranked = await weak_answers(room, ended=EndReason.USER_ENDED, reader=reader)

    # The opening statement carries its own note (#79) — the reader is shown
    # what kind of line each one is, and the first here is somebody making their
    # case rather than answering anything.
    assert [line.notes for line in reader.saw] == [
        (OPENED_THE_ROOM,),
        (),
        (CUT_ACROSS,),
        (),
    ]
    assert ranked.answers == (
        WeakAnswer(
            ordinal=1,
            question="Who inside the company will sponsor this?",
            asked_by="champion",
            answer=None,
            weakness=Weakness.DISMISSED,
            why="A colleague redirected the room before you answered.",
        ),
    )
    assert ranked.usage == TurnUsage(1200, 300)


def test_ninety_seconds_of_silence_gets_no_excuse():
    """The one ending that is the presenter's, and it must not be annotated away.

    `IDLE_TIMEOUT` means no user speech while the panel awaited an answer, for a
    minute and a half. That is not the clock running out on somebody mid-thought;
    it is the most eloquent evasion available, and a room that ends this way
    ended because of it.

    The note exists to stop the model blaming a presenter for the cap. Handing it
    out here would do the opposite — excuse the one silence that is genuinely an
    answer — and a debrief that cannot say so is not an adversarial product.

    Structurally identical to the cap test, one enum value apart. Which is the
    point: the transcripts are indistinguishable and only `ended` separates them.
    """
    room = (
        Said(speaker=USER, text="Revenue tripled last year."),
        Said(speaker="cfo", text="Off what base, and what did it cost?"),
    )

    assert notes_on(room, ended=EndReason.IDLE_TIMEOUT) == {}


def test_the_opening_statement_is_marked_as_one():
    """#79's fourth note, and the reason this module exists.

    An opening statement is the presenter talking with no question above it.
    Shown raw, that reads to a model exactly like the three facts this module
    already restores read — as somebody ducking — and the debrief would tell
    them they dodged a question nobody asked.

    It stays rankable, deliberately: "you spoke for ninety seconds and never
    said what you do" is the highest-leverage thing the product can report,
    because everything downstream inherits it. What the note buys is that the
    model knows which it is looking at.
    """
    room = annotate(
        [
            Said(speaker=USER, text="We move freight for mid-market retailers."),
            Said(speaker="cfo", text="What does each customer cost to acquire?"),
            Said(speaker=USER, text="Around forty pounds."),
        ],
        ended=EndReason.USER_ENDED,
    )

    assert OPENED_THE_ROOM in room[0].notes
    assert OPENED_THE_ROOM not in room[2].notes


def test_only_the_lines_before_anybody_asked_anything_are_the_opening():
    """The opening is everything up to the first panel line, and no further.

    A presenter pauses, so an opening statement is several transcript lines —
    the same reason `OpeningFloor.words` counts across finals rather than per
    final. Marking only the first would leave the rest looking like answers to
    a question that had not been asked yet.
    """
    room = annotate(
        [
            Said(speaker=USER, text="We move freight."),
            Said(speaker=USER, text="Margin is thirty per cent."),
            Said(speaker="cfo", text="Against what volume?"),
        ],
        ended=EndReason.USER_ENDED,
    )

    assert [OPENED_THE_ROOM in line.notes for line in room] == [True, True, False]


def test_a_room_that_opened_with_a_question_marks_nothing():
    """Not every room has an opening statement — a restored session may not.

    The note is a fact about what happened, so it must not be applied on the
    assumption that it did.
    """
    room = annotate(
        [
            Said(speaker="cfo", text="What does each customer cost to acquire?"),
            Said(speaker=USER, text="Around forty pounds."),
        ],
        ended=EndReason.USER_ENDED,
    )

    assert all(OPENED_THE_ROOM not in line.notes for line in room)
