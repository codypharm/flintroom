"""What the room found, read back off a finished transcript.

`Product.md` §3.5 wants a *ranked weak-answer list* — "which questions went
unanswered, which claims lacked support, where the argument contradicted
itself". `docs/debrief-and-sparring.md` decision 2 settles who decides:

    **Code sets the floor; the model only orders what is left.**

#43 measured the alternative. Asked whether the presenter had dodged, a model
said yes on 4 of 4 dodges *and* 4 of 4 genuine answers — a judgement asked in the
absence of a forced choice is not a signal. So the certain cases are computed
here, in ordinary code, from properties of the transcript that are true or false
rather than argued.

Nothing in this module calls a model. That is the same structural refusal
`auditor.py` makes and for the same reason: this is the artifact the coach, the
prep sheet and #55's calibration all read, and a hallucination here would
propagate into all three wearing the authority of a stored record.
"""

from __future__ import annotations

from app.agents.context import USER, Said
from app.agents.weakness import WeakAnswer, Weakness, weak_answers
from app.modules.sessions.schemas import EndReason


def test_a_question_nobody_answered_is_weak():
    """The room moved on and the presenter never spoke. Nobody tried.

    The strongest signal there is, and the only one that needs no interpretation
    at all: it is a property of the *shape* of the transcript rather than of
    anything said in it.

    Load-bearing beyond its obvious use. #54 ships a panel that may open a turn
    by taking issue with a colleague's priorities, which is mildly dismissive by
    nature — measured, a panelist says *"Data ownership is irrelevant without
    margin"* and moves the room onto its own question. The architect accepted
    that on the explicit ground that the safety net is architectural: a question
    waved away in the room is still in the transcript, and this is what reads it
    back. Without this test the product has a panel that can talk a presenter out
    of answering a question a real board would press, and nothing downstream
    catching it.

    The second question here is answered, and must not appear. An implementation
    that returned every question would satisfy the first half of this assertion
    and be worthless.
    """
    room = (
        Said(speaker=USER, text="We rebuilt onboarding and it moved everything."),
        Said(speaker="cfo", text="What did you spend to acquire each customer?"),
        Said(speaker="technical_skeptic", text="What happens at ten times the load?"),
        Said(speaker=USER, text="It holds. We load-tested to twelve times in June."),
    )

    assert weak_answers(room, ended=EndReason.USER_ENDED) == (
        WeakAnswer(
            ordinal=1,
            question="What did you spend to acquire each customer?",
            asked_by="cfo",
            answer=None,
            weakness=Weakness.UNANSWERED,
        ),
    )


def test_an_answer_the_auditor_caught_contradicting_itself_is_the_hardest_evidence():
    """A figure that moved. Not an opinion about the answer — arithmetic.

    The Auditor is the wedge in one object: `auditor.py` refuses to put a model
    anywhere near the comparison precisely so that *"arithmetic hallucination
    becomes impossible rather than discouraged"*. A finding is therefore the one
    weakness in this file that is not a reading of anything — the number was
    seventy and then it was sixty-one, and no judgement is involved in saying so.

    It outranks a press. Both mark the same answer here, and they are not equal
    evidence: a press is a panelist's dissatisfaction, a finding is a
    demonstrable inconsistency. Asserting the precedence rather than leaving it
    to declaration order, because the order of an enum is not a decision anybody
    would think to preserve.

    Why the *routing reason* rather than a stored finding: nothing persists a
    `Finding`, and the panel line that a finding produced already says what the
    contradiction was, in words, grounded — #45 made the composer cite what the
    user actually said. A stored summary would be a second copy of that, free to
    drift from it.
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

    assert weak_answers(room, ended=EndReason.USER_ENDED) == (
        WeakAnswer(
            ordinal=1,
            question="Across which lines?",
            asked_by="cfo",
            answer="Blended it is about sixty-one.",
            weakness=Weakness.CONTRADICTED,
        ),
    )


def test_a_question_the_same_panelist_asked_again_was_answered_badly():
    """The room already judged this one, live, and it judged it insufficient.

    #43 gave a panelist the right to press its own unanswered question once, and
    a panelist exercising it is the best evidence available that an answer did
    not land — better than anything computed afterwards, because it was made with
    the whole room in view by the archetype whose subject it was.

    So this signal is not an opinion about the answer. It is a record of one the
    product already formed and acted on, which is why it belongs in the code
    floor rather than in the model's share of the ranking.

    The second question here *is* answered, with a figure, and nobody presses it
    again. It must not appear — an implementation that flagged every question a
    panelist asked twice in a room would satisfy the first half of this and be
    noise.
    """
    room = (
        Said(speaker=USER, text="Margin held at seventy."),
        Said(speaker="cfo", text="Off what base?"),
        Said(speaker=USER, text="It has been strong all year."),
        Said(speaker="cfo", text="Off what base, though?"),
        Said(speaker=USER, text="Around forty million."),
    )

    assert weak_answers(room, ended=EndReason.USER_ENDED) == (
        WeakAnswer(
            ordinal=1,
            question="Off what base?",
            asked_by="cfo",
            answer="It has been strong all year.",
            weakness=Weakness.PRESSED,
        ),
    )


def test_a_question_a_colleague_waved_away_is_not_the_presenters_fault():
    """Someone else moved the room on. The presenter never got the floor.

    This is the obligation #54 created. The architect chose the audible framing
    of inter-panelist disagreement knowing it is mildly dismissive by nature —
    measured, a CFO says *"Sponsorship matters less than the operational debt of
    that rebuild"* and takes the room with it. That choice was made on the
    explicit ground that the safety net is architectural rather than lexical:
    the waved-away question is still in the transcript, and something downstream
    reads it back.

    This is that something. Without it the product ships a panel that can talk a
    presenter out of answering a question a real board would press, and then
    tells the presenter they dodged it.

    The flag has to be persisted rather than inferred. A disputing line and an
    ordinary one are the same shape once written — both are panel text following
    panel text — so reconstruction would be guesswork about a fact the room knew
    for certain at the time.
    """
    room = (
        Said(speaker=USER, text="Sponsorship is locked in for the year."),
        Said(speaker="champion", text="Who inside the company will sponsor this?"),
        Said(
            speaker="cfo",
            text=(
                "Sponsorship matters less than the operational debt of that "
                "rebuild. What does it cost to carry?"
            ),
            disputed=True,
        ),
        Said(speaker=USER, text="About two engineers full time."),
    )

    assert weak_answers(room, ended=EndReason.USER_ENDED) == (
        WeakAnswer(
            ordinal=1,
            question="Who inside the company will sponsor this?",
            asked_by="champion",
            answer=None,
            weakness=Weakness.DISMISSED,
        ),
    )


def test_the_question_the_room_ended_on_is_not_a_dodge():
    """The clock stopped it, not the presenter.

    Structurally identical to an unanswered question — a panel line with no user
    line after it — and morally the opposite. Telling somebody they ducked a
    question they were never given the chance to answer is exactly the mistake
    #56 exists to prevent, and it would read as the product not having listened.

    It still belongs on the list. §3.5's artifact is *"the 6 questions you will
    get"*, and a question the room ran out of time on is unambiguously one of
    them. What changes is the sentence beside it, which is why the reason travels
    on the record rather than being flattened into a rank.

    Why `ended` has to be passed rather than inferred: a room that stopped at the
    cap and a room that stopped because the presenter sat in silence for ninety
    seconds produce the same final line. Only one of them is a dodge, and the
    transcript cannot tell them apart.
    """
    room = (
        Said(speaker=USER, text="Revenue tripled last year."),
        Said(speaker="cfo", text="Off what base, and what did it cost to get there?"),
    )

    assert weak_answers(room, ended=EndReason.SESSION_CAP) == (
        WeakAnswer(
            ordinal=1,
            question="Off what base, and what did it cost to get there?",
            asked_by="cfo",
            answer=None,
            weakness=Weakness.NOT_REACHED,
        ),
    )
