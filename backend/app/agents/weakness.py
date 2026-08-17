"""Reading a finished room back for what went wrong.

`Product.md` §3.5 ranks weak answers; `docs/debrief-and-sparring.md` decision 2
settles who decides one. **Code sets the floor; the model only orders what is
left.**

#43 is the reason for that division. Asked whether the presenter had dodged, a
model said yes on 4 of 4 dodges *and* 4 of 4 genuine answers — an absolute
judgement offered no alternative is not a signal, it is agreement. So the cases
that can be decided are decided here, from properties of the transcript that are
true or false rather than argued, and the model is left only the comparative
ordering of what remains.

**No model in this module, structurally** — the refusal `auditor.py` makes, for a
sharper reason. This is the artifact the coach, the prep sheet and #55's
calibration all read. A fabrication here does not stay here: it propagates into
three places at once, wearing the authority of a stored record, and the user is
told they fumbled something they never said.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from app.agents.context import USER, Said
from app.modules.sessions.schemas import EndReason


class Weakness(Enum):
    """Why an answer is on the list.

    Carried rather than collapsed into a rank, because the coach has to *say*
    which one it is and the four do not read alike. "Nobody answered this" and
    "you answered without a number in it" are different conversations, and a
    single severity score would leave the coach guessing at which it was holding.
    """

    #: The room moved on and the presenter never spoke.
    UNANSWERED = "unanswered"

    #: The room ended on this question. Structurally identical to `UNANSWERED`
    #: and morally its opposite — the clock stopped it, not the presenter.
    #:
    #: Kept on the list rather than dropped: §3.5's artefact is "the 6 questions
    #: you will get", and a question the room ran out of time on is
    #: unambiguously one of them. Only the sentence beside it changes.
    NOT_REACHED = "not_reached"

    #: The Auditor caught the answer contradicting something already said.
    #:
    #: The only weakness here that is not a reading of anything. `auditor.py`
    #: keeps every comparison in ordinary code specifically so that "arithmetic
    #: hallucination becomes impossible rather than discouraged" — the number was
    #: seventy and then it was sixty-one, and no judgement is involved in saying
    #: so. That is why it outranks a press: one is a panelist's dissatisfaction,
    #: the other is a demonstrable inconsistency.
    CONTRADICTED = "contradicted"

    #: It was answered, and the same panelist asked again.
    #:
    #: The room's own live judgement, made with the whole conversation in view by
    #: the archetype whose subject it was. #43 gave a panelist the right to press
    #: its own unanswered question once, and one exercising that right is better
    #: evidence than anything computed after the fact — which is why this sits in
    #: the code floor rather than in the model's share of the ranking.
    PRESSED = "pressed"

    #: A colleague took issue with its priorities and moved the room on. The
    #: presenter never had the floor.
    #:
    #: The obligation #54 created. The audible framing of inter-panelist
    #: disagreement was chosen knowing it is mildly dismissive, on the ground
    #: that the safety net is architectural rather than lexical — this is that
    #: net, and without it the room can talk somebody out of answering a question
    #: and then blame them for not answering it.
    DISMISSED = "dismissed"


@dataclass(frozen=True)
class WeakAnswer:
    """One question the room did not get a good enough answer to."""

    #: Where the *question* sits in the transcript, counted from zero.
    #:
    #: The question rather than the answer, because the question is what the
    #: coach replays and what sparring re-asks — and because an unanswered
    #: question has no answer line to point at.
    #:
    #: This is a position in the sequence handed to `weak_answers`. The store
    #: passes lines in `ordinal` order, so the mapping is identity; keeping the
    #: statement here rather than assuming it is what lets this module stay
    #: testable without a database.
    ordinal: int

    question: str
    asked_by: str

    #: What the user said in reply, or `None` when they said nothing.
    #:
    #: Kept alongside the question because §3.5's artifact shows "where your
    #: answers are thin", which is unreadable without the answer, and because
    #: sparring compares a re-answer against the original.
    answer: str | None

    weakness: Weakness


def weak_answers(
    transcript: Sequence[Said], *, ended: EndReason
) -> tuple[WeakAnswer, ...]:
    """The ranked list, from a finished room.

    Takes the transcript both sides, in order, exactly as `SessionTranscript`
    returns it — `Said` rather than database rows, so a debrief grounded in a
    finished session and a turn grounded in a live one reason about one shape.

    `ended` is required rather than defaulted, because there is no safe value to
    assume. A room that stopped at the cap and a room that stopped because the
    presenter sat in silence produce an identical final line, and only one of
    them is a dodge. A default would pick one of those readings for every caller
    that forgot to think about it, silently.
    """
    weak: list[WeakAnswer] = []
    last_question = _last_question_in(transcript)

    for ordinal, line in enumerate(transcript):
        if line.speaker == USER:
            continue

        answer = _answer_to(transcript, ordinal)
        weakness = (
            _why(transcript, ordinal, last_question, ended)
            if answer is None
            else _how_the_answer_went(transcript, ordinal)
        )
        if weakness is None:
            continue

        weak.append(
            WeakAnswer(
                ordinal=ordinal,
                question=line.text,
                asked_by=line.speaker,
                answer=answer,
                weakness=weakness,
            )
        )

    return tuple(weak)


def _how_the_answer_went(
    transcript: Sequence[Said], ordinal: int
) -> Weakness | None:
    """What is wrong with the answer that was given, or `None` if nothing is.

    Separate from `_why` because the two families are not comparable. `_why`
    settles *whose* silence a missing answer was; this one reads an answer that
    exists. Collapsing them would put "nobody spoke" and "the number was vague"
    on one scale, and the coach has to say which it is holding.
    """
    if _interrupted_by_the_auditor(transcript, ordinal):
        return Weakness.CONTRADICTED
    if _pressed(transcript, ordinal):
        return Weakness.PRESSED
    return None


def _interrupted_by_the_auditor(transcript: Sequence[Said], ordinal: int) -> bool:
    """Whether a finding is what handed the next panelist the floor.

    Which means the Auditor caught something in the answer to *this* question —
    the turn it routes is always the one that follows the utterance it read.
    """
    caught = _next_question_after(transcript, ordinal)
    return caught is not None and transcript[caught].chosen_by == "finding"


def _pressed(transcript: Sequence[Said], ordinal: int) -> bool:
    """Whether the panelist who asked this asked again straight after.

    The next *question*, not the next line — an answer sits between them by
    definition, which is what separates a press from #54's dispute. A dispute is
    panel text immediately following panel text; a press is the same archetype
    coming back around after hearing the reply and not being satisfied by it.

    Only the immediately following question counts. A panelist returning to a
    subject four turns later is a room circling, not a room judging one answer.
    """
    asked_again = _next_question_after(transcript, ordinal)
    return (
        asked_again is not None
        and transcript[asked_again].speaker == transcript[ordinal].speaker
    )


def _next_question_after(transcript: Sequence[Said], ordinal: int) -> int | None:
    """Where the panel speaks next, or `None` if this was the room's last word."""
    for candidate in range(ordinal + 1, len(transcript)):
        if transcript[candidate].speaker != USER:
            return candidate
    return None


def _why(
    transcript: Sequence[Said],
    ordinal: int,
    last_question: int | None,
    ended: EndReason,
) -> Weakness:
    """Which of the three unanswered readings this is.

    All three look identical in the transcript — a panel line with no user line
    after it — and only one of them is the presenter's fault. Ordered so the
    exonerating readings are tested first, because the cost of the two mistakes
    is not symmetric: calling a dodge something else understates one line of a
    debrief, and calling something else a dodge accuses somebody of ducking a
    question they were never allowed to answer.
    """
    if _disputed_next(transcript, ordinal):
        return Weakness.DISMISSED
    if ordinal == last_question and not _went_silent(ended):
        return Weakness.NOT_REACHED
    return Weakness.UNANSWERED


def _disputed_next(transcript: Sequence[Said], ordinal: int) -> bool:
    """Whether the panel line that followed this one took issue with it.

    Only the immediately following line, matching `dispute.contested`, which
    offers a panelist only the line just spoken. A dispute two turns later is
    not what moved the room off this question.
    """
    following = transcript[ordinal + 1 :]
    return bool(following) and following[0].disputed


def _went_silent(ended: EndReason) -> bool:
    """Whether the room ended because the presenter stopped speaking.

    The one end reason under which a hanging final question *is* the presenter's
    to answer for. `IDLE_TIMEOUT` means no user speech while the panel awaited an
    answer — ninety seconds of it — and silence that long in front of a question
    is the most eloquent dodge available.
    """
    return ended is EndReason.IDLE_TIMEOUT


def _last_question_in(transcript: Sequence[Said]) -> int | None:
    """Where the room's final question sits, or `None` if it asked none.

    The final *question*, not the final line: a room that ended with the user
    still talking has no hanging question, and its last panel line was answered
    by definition.
    """
    for ordinal in reversed(range(len(transcript))):
        if transcript[ordinal].speaker != USER:
            return ordinal
    return None


def _answer_to(transcript: Sequence[Said], ordinal: int) -> str | None:
    """What the user said to the question at `ordinal`, if anything.

    Everything up to the next panel line, because a presenter answering a hard
    question pauses, and a pause is two transcript lines rather than one. Reading
    only the line immediately after would score somebody as unanswered for
    breathing.
    """
    spoken = [
        line.text
        for line in _until_the_room_speaks_again(transcript, ordinal)
        if line.speaker == USER
    ]
    return " ".join(spoken) if spoken else None


def _until_the_room_speaks_again(
    transcript: Sequence[Said], ordinal: int
) -> list[Said]:
    """The lines between this question and whatever the panel said next."""
    following: list[Said] = []

    for line in transcript[ordinal + 1 :]:
        if line.speaker != USER:
            break
        following.append(line)

    return following
