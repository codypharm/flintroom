"""'Come again?' gets the same question back, from the same voice.

Observed on the first Play build (Kettleworks run, 2026-08-26): the presenter
asked a panelist to repeat themselves, and a *different* panelist re-delivered
their own earlier question instead. The room had no concept of a repeat — the
request was routed like any fresh utterance, and selection did what selection
does with an ambiguous line.

The fix is deterministic, like the reentry it mirrors: recognising the request
is arithmetic over words, and honouring it is the last panel line said again
verbatim — no selection, no composer, nothing invented.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.archetypes import DEFAULT_PANEL
from app.agents.context import Grounding, Said, USER
from app.agents.repeat import asked_to_rephrase, asked_to_repeat, question_to_repeat
from app.modules.voice.events import AgentTranscript
from app.modules.voice.orchestrated import OrchestratedChannel
from app.modules.voice.transcription import Transcription

from tests.test_orchestrated_channel import (
    FakeTranscript,
    FakeTranscription,
    ScriptedPanelModel,
    events_of,
    mid_room,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- recognising


@pytest.mark.parametrize(
    "said",
    [
        "come again",
        "Come again?",
        "sorry, say that again",
        "can you repeat that",
        "Could you repeat the question?",
        "what was that",
        "pardon?",
        "what?",
        "sorry?",
        "one more time please",
        "I didn't catch that",
        "i didn't hear you",
        "say that again",
        "huh?",
    ],
)
def test_a_repeat_request_is_recognised(said: str):
    assert asked_to_repeat(said)


@pytest.mark.parametrize(
    "said",
    [
        # Contains a trigger phrase but is plainly an answer, not a request —
        # a false positive here replays a question over somebody mid-argument.
        "I'll come again to that point once I've covered churn",
        "we can repeat that success in the European market",
        "what matters here is the margin, not the headline number",
        "sorry, the number I gave earlier was wrong — it's thirty-eight",
        "what our customers say is that the callout takes four days",
        "the question of pricing is one we've studied for a year",
        "",
    ],
)
def test_an_answer_is_never_mistaken_for_a_repeat_request(said: str):
    assert not asked_to_repeat(said)


# ------------------------------------------------------- did not understand


@pytest.mark.parametrize(
    "said",
    [
        "can you rephrase that",
        "Rephrase that?",
        "could you rephrase the question",
        "rephrase",
        "what do you mean",
        "what do you mean by that?",
        "sorry, what do you mean",
        "I don't understand",
        "i dont understand the question",
        "put that another way",
        "can you put that another way",
        "say that another way",
        "in plain english?",
        "I'm not sure what you're asking",
        "not sure what you're asking",
    ],
)
def test_a_rephrase_request_is_recognised(said: str):
    """Reported by a tester 2026-09-01, and the reason this half exists.

    Every pattern in `asked_to_repeat` is a variant of *I did not hear you*.
    None of them is *I did not understand you*, so "can you rephrase that" fell
    through to selection and a different panelist took the floor — the exact
    failure the repeat path was written to fix, arriving through the door it
    did not cover.
    """
    assert asked_to_rephrase(said)


@pytest.mark.parametrize(
    "said",
    [
        # Plainly answers, and a false positive here re-asks a question over
        # somebody mid-argument — the same cost the repeat side guards against.
        "I don't understand why the market has not moved on this yet",
        "what I mean is that churn is concentrated in the first month",
        "we can put that another way of working in front of the board",
        "let me rephrase my earlier answer about the margin",
        "in plain english the unit economics work at scale",
        "",
    ],
)
def test_an_answer_is_never_mistaken_for_a_rephrase_request(said: str):
    assert not asked_to_rephrase(said)


@pytest.mark.parametrize(
    "said",
    [
        "come again",
        "pardon?",
        "what?",
        "one more time please",
        "I didn't catch that",
    ],
)
def test_hearing_and_understanding_are_told_apart(said: str):
    """The two requests want opposite things, so they must not overlap.

    A misfiled *did not hear* costs a composer call and a re-wording nobody
    wanted. A misfiled *did not understand* gets the identical words back,
    which is the failure this task exists to fix.
    """
    assert asked_to_repeat(said)
    assert not asked_to_rephrase(said)


def test_a_rephrase_request_is_not_also_a_repeat_request():
    for said in ("can you rephrase that", "what do you mean", "I don't understand"):
        assert asked_to_rephrase(said)
        assert not asked_to_repeat(said)


# ------------------------------------------------------------- what to repeat


def test_the_question_to_repeat_is_the_last_panel_line():
    transcript = [
        Said(speaker=USER, text="Our margin is sixty percent."),
        Said(speaker="cfo", text="Your deck says 38. Which is it?"),
        Said(speaker=USER, text="come again"),
    ]

    line = question_to_repeat(transcript)

    assert line is not None
    assert line.speaker == "cfo"
    assert line.text == "Your deck says 38. Which is it?"


def test_a_room_where_nobody_has_asked_anything_has_nothing_to_repeat():
    assert question_to_repeat([]) is None
    assert question_to_repeat([Said(speaker=USER, text="come again")]) is None


# ------------------------------------------------------------------- the room


class AfterTheQuestion(FakeTranscription):
    """Speaks the second line only once the first question has been asked.

    Two back-to-back finals would have the request *barge in on* the question —
    a different scenario. A person asks for a repeat after hearing (or failing
    to hear) the question, so the fake waits for it to reach the transcript.
    """

    def __init__(self, first, second, *, store: FakeTranscript) -> None:
        super().__init__([])
        self._first, self._second, self._store = first, second, store

    async def results(self):
        yield self._first
        while not any(line.speaker != USER for line in self._store.lines):
            await asyncio.sleep(0)
        yield self._second


async def test_come_again_replays_the_question_verbatim_from_the_same_voice():
    """One question, one repeat request, the same words again — and no model.

    The composer is called once, for the original question. The repeat is a
    re-delivery, not a paraphrase: a second composition would be a model call
    about nothing, and a differently-worded question that the debrief would
    read as two.
    """
    model = ScriptedPanelModel(line="Walk me through that margin number.")
    store = FakeTranscript()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=AfterTheQuestion(
            Transcription(text="Our margin is north of sixty percent.", final=True),
            Transcription(text="sorry, come again?", final=True),
            store=store,
        ),
        model=model,
        grounding=Grounding(),
        floor=mid_room(),
        transcript=store,
    )

    events = await events_of(channel)

    spoken = [event.text for event in events if isinstance(event, AgentTranscript)]
    assert spoken == [
        "Walk me through that margin number.",
        "Walk me through that margin number.",
    ]
    # Composed once. The second delivery cost synthesis, never a model call.
    assert model.composed_for == ["cfo"]

    # Not re-persisted: like the opener and the reentry, a re-delivery is
    # procedure rather than conversation, and a re-recorded line would read
    # downstream as a question asked twice.
    panel_lines = [line for line in store.lines if line.speaker != USER]
    assert len(panel_lines) == 1


async def test_a_rephrase_request_does_not_hand_the_floor_to_somebody_else():
    """The tester's report, 2026-09-01 — and the half of it that ships now.

    They asked the panelist to rephrase and a *different* panelist took over,
    because every pattern in `asked_to_repeat` means *I did not hear you* and
    theirs meant *I did not understand you*. The utterance matched nothing and
    selection routed it like an answer.

    What is asserted here is the interruption gone, not the confusion solved.
    The resolved design on #117 is a composed re-wording, and this is
    deliberately the wrong answer shipped ahead of the right one: somebody who
    did not follow the words does not want the identical words back. But the
    composed version touches nine files including a migration, all in this hot
    path, and a stranger interrupting a request for help is the part that reads
    as broken.

    **This test is expected to change when that lands** — the assertion that
    the same voice answers stays; the one that the words are identical does not.
    """
    model = ScriptedPanelModel(line="Walk me through that margin number.")
    store = FakeTranscript()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=AfterTheQuestion(
            Transcription(text="Our margin is north of sixty percent.", final=True),
            Transcription(text="can you rephrase that?", final=True),
            store=store,
        ),
        model=model,
        grounding=Grounding(),
        floor=mid_room(),
        transcript=store,
    )

    events = await events_of(channel)
    spoken = [event for event in events if isinstance(event, AgentTranscript)]

    # One voice, twice — never a second panelist answering a request for help.
    assert [event.speaker for event in spoken] == ["cfo", "cfo"]
    # Composed once. The re-delivery costs synthesis, not a model call.
    assert model.composed_for == ["cfo"]
