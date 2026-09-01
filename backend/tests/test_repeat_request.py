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
from app.agents.model import ModelReply
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


class SlowToRephrase(ScriptedPanelModel):
    """Never answers a rephrase, so the deadline is what ends the wait."""

    async def compose(self, *, archetype, context, finding=None, dispute=None, rephrasing=None):
        if rephrasing is not None:
            await asyncio.sleep(3600)
        return await super().compose(
            archetype=archetype, context=context, finding=finding, dispute=dispute
        )


class BrokenRephrase(ScriptedPanelModel):
    """Fails a rephrase the way a provider does — after the room is committed."""

    def __init__(self, *, reply: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._reply = reply

    async def compose(self, *, archetype, context, finding=None, dispute=None, rephrasing=None):
        if rephrasing is not None:
            if self._reply is None:
                raise RuntimeError("provider said no")
            return ModelReply(text=self._reply)
        return await super().compose(
            archetype=archetype, context=context, finding=finding, dispute=dispute
        )


async def _room(model, *, second: str, store: FakeTranscript | None = None):
    """One question, then whatever the presenter says next."""
    store = store if store is not None else FakeTranscript()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=AfterTheQuestion(
            Transcription(text="Our margin is north of sixty percent.", final=True),
            Transcription(text=second, final=True),
            store=store,
        ),
        model=model,
        grounding=Grounding(),
        floor=mid_room(),
        transcript=store,
    )
    return await events_of(channel), store


async def test_a_rephrase_is_put_again_by_the_same_panelist_in_new_words():
    """The tester's report, answered — #117, 2026-09-01.

    They asked for a rephrase and a *different* panelist took the floor. Now
    the panelist who asked puts it again, and in different words: returning the
    identical sentence to somebody who has just said they did not follow reads
    as the panel ignoring them twice.
    """
    model = ScriptedPanelModel(
        line="Walk me through that margin number.",
        rephrased="Which number is the sixty — gross or net?",
    )

    events, _ = await _room(model, second="can you rephrase that?")
    spoken = [event for event in events if isinstance(event, AgentTranscript)]

    assert [event.speaker for event in spoken] == ["cfo", "cfo"]
    assert [event.text for event in spoken] == [
        "Walk me through that margin number.",
        "Which number is the sixty — gross or net?",
    ]


async def test_the_rephrase_is_composed_against_the_question_already_asked():
    """The substance is held by construction, not by a prompt asking nicely.

    What the composer is handed is the original line itself. With only that
    sentence in front of it there is nothing else to ask about — which is why
    `_rephrasing_prompt` carries no claims, no transcript and no finding. #45
    is the standing warning about showing a composer material it does not need.
    """
    model = ScriptedPanelModel(line="Walk me through that margin number.")

    await _room(model, second="what do you mean")

    assert model.rephrasings == ["Walk me through that margin number."]


async def test_the_rephrase_is_recorded_and_marked_as_one():
    """Persisted because they answer *these* words; marked because of #56.

    Unmarked, the original question would sit in the transcript with no answer
    after it and rank as the strongest weak answer there is — the one nobody
    even tried — telling somebody they ducked a question they had asked to have
    re-put and then answered.
    """
    model = ScriptedPanelModel(line="Walk me through that margin number.", rephrased="Gross or net?")

    _, store = await _room(model, second="I don't understand")
    panel_lines = [line for line in store.lines if line.speaker != USER]

    assert [line.text for line in panel_lines] == [
        "Walk me through that margin number.",
        "Gross or net?",
    ]
    assert [line.rephrasing for line in panel_lines] == [False, True]


async def test_a_slow_rephrase_falls_back_to_the_words_already_said():
    """It degrades to the free version, never to silence.

    Open Risk #3 puts the illusion at ~1.5s. A replay is instant and a model
    call is not, and the pause lands where the presenter is already confused —
    so the deadline hands back the answer that shipped first rather than
    waiting on a provider that is not coming.
    """
    model = SlowToRephrase(line="Walk me through that margin number.")

    events, _ = await _room(model, second="can you rephrase that?")
    spoken = [event.text for event in events if isinstance(event, AgentTranscript)]

    assert spoken == [
        "Walk me through that margin number.",
        "Walk me through that margin number.",
    ]


@pytest.mark.parametrize("reply", [None, "", "   "])
async def test_a_failed_or_empty_rephrase_falls_back_the_same_way(reply):
    """A raised provider error and a reply with nothing in it are one case.

    Both mean no new words exist, and both have the same correct answer. This
    is the only broad `except` in the channel, and it is justified by there
    being a free fallback — unlike a turn, where failing the room is honest.
    """
    model = BrokenRephrase(reply=reply, line="Walk me through that margin number.")

    events, _ = await _room(model, second="can you rephrase that?")
    spoken = [event for event in events if isinstance(event, AgentTranscript)]

    assert [event.speaker for event in spoken] == ["cfo", "cfo"]
    assert [event.text for event in spoken] == [
        "Walk me through that margin number.",
        "Walk me through that margin number.",
    ]


async def test_a_rephrase_of_a_rephrase_gets_the_words_verbatim():
    """Composed once per question, and the second request is not the words.

    Re-wording a re-wording drifts further from the original each pass, and
    somebody asking twice usually needs the panelist to move on rather than to
    try a third phrasing.
    """
    model = ScriptedPanelModel(line="Walk me through that margin number.", rephrased="Gross or net?")
    store = FakeTranscript()
    channel = OrchestratedChannel(
        panel=DEFAULT_PANEL,
        transcription=AfterTheQuestion(
            Transcription(text="Our margin is north of sixty percent.", final=True),
            Transcription(text="can you rephrase that?", final=True),
            store=store,
        ),
        model=model,
        grounding=Grounding(
            transcript=(
                Said(speaker=USER, text="Our margin is sixty."),
                Said(speaker="cfo", text="Walk me through that margin number."),
            )
        ),
        floor=mid_room(),
        transcript=store,
    )
    channel._rephrased.add("Walk me through that margin number.")

    events = await events_of(channel)
    spoken = [event.text for event in events if isinstance(event, AgentTranscript)]

    assert model.rephrasings == []
    assert spoken[-1] == "Walk me through that margin number."
