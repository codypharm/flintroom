"""What somebody said about their meeting, and the room it becomes.

`docs/onboarding.md` promises the survey configures the product rather than
segmenting the user, and its testing note asks for the assertion that proves it:
*"the reveal has to match the room — an assertion on the archetypes selected for
a given answer set, not on the UI."* This file is where that assertion lives.

The answers split by **lifetime**, decided with the architect on 2026-08-18.
Role and audience are durable — they describe how this person is usually
received, and they outlive any one meeting. The situation and its date are an
*event*, and events pass: "Board review in 6 days" is true this week and false
next, so it is a row per occasion rather than a field that gets overwritten.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.modules.onboarding.schemas import Answers
from app.modules.onboarding.service import OnboardingService

pytestmark = pytest.mark.asyncio


async def test_the_answers_given_at_signup_are_the_room_that_gets_seated(db):
    """The tracer bullet, and the whole promise of the reveal in one assertion.

    Two chairs placed and a role, against three seats. The placed chairs come
    back in the order they were placed; the empty one is filled from the role,
    skipping the two already seated. Nobody is asked twice and nothing is
    re-sorted.
    """
    user_id = uuid.uuid4()

    await OnboardingService(db).record(
        user_id=user_id,
        answers=Answers(
            situation="board_review",
            happens_on=date(2026, 9, 1),
            role="exec",
            audience=["budget", "rival"],
        ),
    )

    seated = await OnboardingService(db).room_for(user_id=user_id, seats=3)

    assert [archetype.name for archetype in seated] == [
        "cfo",
        "internal_blocker",
        "distracted_executive",
    ]
