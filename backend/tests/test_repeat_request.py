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
from app.agents.repeat import asked_to_repeat, question_to_repeat
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
