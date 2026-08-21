"""What a resumed debrief screen gets back. #83.

`read_debrief`'s own docstring promises that the read is idempotent "because
backgrounding and resuming re-fetches" — and it is, for the ranked list. For
everything the *user* produced it was a reset: every question they asked the
coach, every reply, every re-answer, gone the moment the phone backgrounded or
they tapped back and forward.

The conversation was never lost. `session_coach_turns` and
`session_sparring_attempts` have held it since #58 and #59; the endpoint simply
never handed it back, and the client kept it in `useState`. So the findings
redrew and the conversation did not.

Why nobody noticed: the debrief screen was built and tested inside one screen
life, and #57's idempotency work was about not paying for a second reasoning
call — which it achieves. Nothing tested what a *resumed* screen shows.

**No new model calls and no synthesis.** This is stored text. `speech` comes
back empty for the same reason the opening's does — `docs/voice-cost.md` puts
the expressive speaker at roughly a minute of live interrogation per spoken
reply, and this endpoint is what a backgrounded phone re-fetches. The client
already draws its replay control only when there are bytes to play.
"""

from __future__ import annotations

import pytest

from app.agents.context import USER, Said
from app.modules.sessions.models import CoachTurn, SparringAttempt

from tests.test_debrief import room_that_happened
from tests.test_debrief_endpoint import FOUND, ROOM

pytestmark = pytest.mark.asyncio

COACH = "coach"


async def a_room_with_a_conversation(
    db, engine, sessions, settlement, funded_account, weakness_reader
):
    """A settled room whose coaching thread and sparring are already on disk.

    Written directly rather than driven through the coach, because what is
    under test is the *read* — driving it would exercise a model, a
    synthesiser and this endpoint at once, and a failure would not say which.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    weakness_reader.judged = (FOUND,)

    db.add_all(
        [
            # Ordinal 0 is the greeting, written by `_greeted`. It has its own
            # field on the response and must not appear twice.
            CoachTurn(session_id=session.id, ordinal=0, who=COACH, text="Let's begin."),
            CoachTurn(
                session_id=session.id, ordinal=1, who=USER, text="Why was that weak?"
            ),
            CoachTurn(
                session_id=session.id,
                ordinal=2,
                who=COACH,
                text="You gave him a feeling where he asked for a base.",
            ),
        ]
    )
    db.add(
        SparringAttempt(
            session_id=session.id,
            weak_rank=0,
            attempt=0,
            said="We grew from four hundred accounts to five sixty.",
            reply="That is a base. He can price it now.",
        )
    )
    await db.commit()
    return session


async def test_a_resumed_screen_gets_the_conversation_back(
    client, db, engine, sessions, settlement, funded_account, bearer, weakness_reader
):
    """THE BUG. Every question asked and every reply, gone on resume."""
    session = await a_room_with_a_conversation(
        db, engine, sessions, settlement, funded_account, weakness_reader
    )

    body = (
        await client.get(
            f"/v1/sessions/{session.id}/debrief",
            headers=bearer(funded_account.user_id),
        )
    ).json()

    assert [(turn["heard"], turn["text"]) for turn in body["thread"]] == [
        ("Why was that weak?", "You gave him a feeling where he asked for a base.")
    ]


async def test_the_greeting_does_not_appear_twice(
    client, db, engine, sessions, settlement, funded_account, bearer, weakness_reader
):
    """It has its own field, and a thread that repeated it would render the
    coach greeting the user in the middle of their own conversation."""
    session = await a_room_with_a_conversation(
        db, engine, sessions, settlement, funded_account, weakness_reader
    )

    body = (
        await client.get(
            f"/v1/sessions/{session.id}/debrief",
            headers=bearer(funded_account.user_id),
        )
    ).json()

    assert all("begin" not in turn["text"] for turn in body["thread"])


async def test_the_re_answers_come_back_anchored_to_their_question(
    client, db, engine, sessions, settlement, funded_account, bearer, weakness_reader
):
    """`weak_rank` is what the client keys attempts by, per #59, and it is also
    the fence: a sparring turn is only ever about a stored rank."""
    session = await a_room_with_a_conversation(
        db, engine, sessions, settlement, funded_account, weakness_reader
    )

    body = (
        await client.get(
            f"/v1/sessions/{session.id}/debrief",
            headers=bearer(funded_account.user_id),
        )
    ).json()

    assert body["attempts"] == [
        {
            "weak_rank": 0,
            "attempt": 0,
            "heard": "We grew from four hundred accounts to five sixty.",
            "text": "That is a base. He can price it now.",
            "speech": "",
        }
    ]


async def test_nothing_is_spoken_again_on_a_read(
    client, db, engine, sessions, settlement, funded_account, bearer, weakness_reader
):
    """The cost rule, and the reason this is stored text rather than audio.

    A spoken reply costs about a minute of live interrogation, and this is the
    endpoint a backgrounded phone re-fetches. Returning audio here would bill a
    synthesis vendor every time somebody switched apps.
    """
    session = await a_room_with_a_conversation(
        db, engine, sessions, settlement, funded_account, weakness_reader
    )

    body = (
        await client.get(
            f"/v1/sessions/{session.id}/debrief",
            headers=bearer(funded_account.user_id),
        )
    ).json()

    assert all(turn["speech"] == "" for turn in body["thread"])
    assert all(turn["speech"] == "" for turn in body["attempts"])


async def test_a_room_nobody_has_talked_to_comes_back_empty_rather_than_absent(
    client, db, engine, sessions, settlement, funded_account, bearer, weakness_reader
):
    """An empty list is a real answer — the same call `DebriefRead` already
    makes for `weak_answers`. A client that had to branch on a missing key
    would branch on it wrongly somewhere."""
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    weakness_reader.judged = (FOUND,)

    body = (
        await client.get(
            f"/v1/sessions/{session.id}/debrief",
            headers=bearer(funded_account.user_id),
        )
    ).json()

    assert body["thread"] == []
    assert body["attempts"] == []
