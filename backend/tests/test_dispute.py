"""When one panelist may take issue with another's priorities.

`Product.md` §3.1 asks for a mixed room whose members "disagree with each other",
and until now every line was addressed to the presenter — the champion and the
CFO never noticed each other existed.

The shape was settled with the architect on 2026-08-17 and the division is the
whole design: **code owns the occasion, the panelist owns the substance.** Code
answers only "is this a turn where a difference may be voiced"; it never decides
what the difference is, never names a colleague's error, never writes a line.

Two bounds come out of that conversation and both live here rather than in a
prompt, because #43 measured what happens when a model is asked to judge whether
a rule applies: it says yes, every time.

- **Priority only, never substance.** A panelist may say margin is not what
  sinks this; it may not say the CFO's margin challenge was wrong. The
  presenter still owes both answers. A panel that can excuse somebody from a
  question is the delivery-coach failure the wedge exists to refuse.
- **Capped per room.** Two agents allowed to differ whenever they like produce
  a room that argues instead of interrogating.
"""

from __future__ import annotations

from dataclasses import replace

from app.agents.archetypes import Archetype, DEFAULT_PANEL, by_name
from app.agents.difficulty import GENTLE, pressure_at
from app.agents.context import USER, Grounding, Said, TurnContext
import pytest

from app.agents.dispute import DISPUTES_PER_ROOM, contested
from app.agents.model import ModelReply
from app.agents.panel import interrogate

CFO = by_name("cfo")
SKEPTIC = by_name("technical_skeptic")
CHAMPION = by_name("champion")


def room(*lines: tuple[str, str]) -> TurnContext:
    return TurnContext(
        said="We rebuilt onboarding and it moved everything.",
        grounding=Grounding(
            transcript=tuple(Said(speaker=who, text=what) for who, what in lines)
        ),
    )


def test_nobody_disputes_an_empty_room():
    """The first question of a session has nothing to differ from."""
    assert contested(CFO, DEFAULT_PANEL, room(), spent=0) is None


def test_a_panelist_does_not_dispute_itself():
    """A panelist can already speak twice running — #43 lets one press its own
    unanswered question, once. On that second turn the previous speaker is
    itself, and a panelist taking issue with its own priorities is not a room
    disagreeing, it is an archetype with no thesis.

    The two features are mutually exclusive by construction rather than by a
    rule that has to be remembered.
    """
    said = room((USER, "Margin held."), ("cfo", "Where does that come from?"))

    assert contested(CFO, DEFAULT_PANEL, said, spent=0) is None


def test_a_panelist_disputes_somebody_who_cares_about_other_things():
    """Different domains is the whole trigger, and it is checkable in data that
    already exists for the Auditor's targeted interruption.

    No declared rivalries. Nothing is hardcoded about who argues with whom, so
    the fault line that emerges came from what was actually said rather than
    from a script.
    """
    said = room(
        # She has already had a turn, which is what earns her a position to
        # assert — see `test_nobody_disputes_before_they_have_said_anything`.
        ("technical_skeptic", "What breaks at ten times the load?"),
        (USER, "Margin held."),
        ("cfo", "Where does that come from?"),
    )

    assert contested(SKEPTIC, DEFAULT_PANEL, said, spent=0) == Said(
        speaker="cfo", text="Where does that come from?"
    )


def test_two_panelists_who_want_the_same_things_have_nothing_to_differ_about():
    """Overlapping domains means agreement, not a manufactured split.

    This is the gate against the room arguing on schedule: a panelist whose
    ground is the same ground has no priority to assert against it, and being
    told to find one anyway is how a disagreement becomes theatre.
    """
    twin = Archetype(
        name="second_cfo",
        title="Another CFO",
        blurb="Also about the money.",
        persona="You care about unit economics.",
        attack_strategy="Attack margin.",
        domains=CFO.domains,
    )
    said = room((USER, "Margin held."), ("cfo", "Where does that come from?"))

    assert contested(twin, (*DEFAULT_PANEL, twin), said, spent=0) is None


def test_an_archetype_with_no_ground_of_its_own_never_disputes():
    """The Distracted Executive has no domains, deliberately — its complaint is
    that you are not making the point clearly, which is not a subject.

    Nothing was added for this. It falls out of reading the same `domains` the
    Auditor routes on, which is the argument for using that field rather than
    inventing a second one.
    """
    vague = Archetype(
        name="distracted",
        title="The Distracted Executive",
        blurb="Wants the point in one sentence.",
        persona="You are half-listening.",
        attack_strategy="Demand the point.",
    )
    said = room((USER, "Margin held."), ("cfo", "Where does that come from?"))

    assert contested(vague, (*DEFAULT_PANEL, vague), said, spent=0) is None


def test_the_room_stops_disagreeing_once_it_has_had_its_share():
    """The cap is in code because a model asked to self-limit does not.

    #43 measured that directly: asked whether the presenter had dodged, it said
    yes on 4 of 4 dodges and 4 of 4 genuine answers. A bound that lives in the
    instruction is a bound that is not there.
    """
    said = room(
        # She has spoken, which is what earns a position to assert (#81).
        ("technical_skeptic", "What breaks at scale?"),
        (USER, "Margin held."),
        ("cfo", "Where does that come from?"),
    )

    assert contested(SKEPTIC, DEFAULT_PANEL, said, spent=DISPUTES_PER_ROOM) is None


class Watching:
    """A model that records what it was handed."""

    def __init__(self) -> None:
        self.disputed: list[object] = []

    async def select(self, *, candidates, context):
        return ModelReply(text="technical_skeptic")

    async def compose(self, *, archetype, context, finding=None, dispute=None):
        self.disputed.append(dispute)
        return ModelReply(text="Churn is what sinks this. What has it done?")


@pytest.mark.asyncio
async def test_the_turn_carries_the_line_it_is_taking_issue_with():
    """`interrogate` decides the occasion and hands it down.

    Asserted on what the model was given rather than on internals, because the
    claim is that the composer knows — a gate that computed the right answer and
    did not pass it on would look identical from outside.
    """
    model = Watching()

    turn = await interrogate(
        DEFAULT_PANEL,
        said="We rebuilt onboarding and it moved everything.",
        model=model,
        grounding=Grounding(
            transcript=(
                # She has spoken, which is what earns a position to assert (#81).
                Said(speaker="technical_skeptic", text="What breaks at scale?"),
                Said(speaker=USER, text="Margin held."),
                Said(speaker="cfo", text="Where does that come from?"),
            )
        ),
    )

    assert model.disputed == [Said(speaker="cfo", text="Where does that come from?")]
    assert turn.disputed is True


@pytest.mark.asyncio
async def test_a_room_that_has_had_its_disagreements_gets_no_more():
    """The cap reaches the turn, not just the gate.

    `interrogate` is where `spent` is applied, so a caller that tracked the
    count and never passed it would produce a room with no limit at all —
    silently, because every individual turn would still look correct.
    """
    model = Watching()

    turn = await interrogate(
        DEFAULT_PANEL,
        said="We rebuilt onboarding and it moved everything.",
        model=model,
        grounding=Grounding(
            transcript=(
                Said(speaker=USER, text="Margin held."),
                Said(speaker="cfo", text="Where does that come from?"),
            )
        ),
        disputes_spent=DISPUTES_PER_ROOM,
    )

    assert model.disputed == [None]
    assert turn.disputed is False


def test_the_gentle_rung_lets_nobody_be_talked_over():
    """#55's floor, and the reason the floor softens *this* rather than the press.

    A first session is level 1, and being cut across by a colleague is the
    mildly dismissive turn #54 introduced — measured, a panelist says "Data
    ownership is irrelevant without margin" and moves the room onto its own
    question. That is fair to somebody on their fourth session and it is
    `Product.md` §434's humiliation on their first: *"Hostility is the product;
    humiliation is the churn."*

    Read from the room's own rung rather than the module constant, which is the
    whole change: the cap is a property of who is being interrogated, not of the
    build.
    """
    said = room(
        # She has spoken, which is what earns a position to assert (#81).
        ("technical_skeptic", "What breaks at scale?"),
        (USER, "Margin held."),
        ("cfo", "Where does that come from?"),
    )
    gentle = replace(said, pressure=pressure_at(GENTLE))

    assert contested(SKEPTIC, DEFAULT_PANEL, said, spent=0) is not None
    assert contested(SKEPTIC, DEFAULT_PANEL, gentle, spent=0) is None


def test_nobody_disputes_before_they_have_said_anything():
    """#81. You cannot claim your priority matters more before you have stated it.

    Room dda2fc9c: the Technical Skeptic's FIRST line in the room was a dispute
    — "The arithmetic matters less than what happens when the connection
    drops" — in a conversation with no technology in it at all. She then
    invented some.

    The four gates all passed, and the fourth is why: non-overlapping domains
    was treated as evidence a disagreement was legitimate. It is the opposite.
    Two archetypes with nothing in common are the MOST likely to produce a
    non-sequitur.

    **This gate uses selection's own judgement rather than a second weak
    signal.** A panelist who has already spoken was chosen by the routing model
    at least once, so they have established ground in this room. Matching
    domains against speech was the alternative, and it is the 53%-accurate
    keyword routing #43 measured and rejected — reusing it as a refusal is the
    same signal wearing a different hat.
    """
    said = room((USER, "Margin held."), ("cfo", "Where does that come from?"))

    assert contested(SKEPTIC, DEFAULT_PANEL, said, spent=0) is None


def test_a_panelist_who_has_taken_a_position_may_say_it_matters_more():
    """The other side of it, and what keeps #54 alive.

    Once somebody has had a turn they have a stated priority, and asserting it
    outranks a colleague's is the disagreement the room is for. This is the
    ordinary case; the one above is the theatrical one.
    """
    said = room(
        (USER, "Margin held."),
        ("technical_skeptic", "What breaks at ten times the load?"),
        (USER, "Nothing so far."),
        ("cfo", "Where does that margin come from?"),
    )

    assert contested(SKEPTIC, DEFAULT_PANEL, said, spent=0) == Said(
        speaker="cfo", text="Where does that margin come from?"
    )
