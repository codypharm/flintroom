"""What the presenter said about the room they are walking into.

#66, and the permitted half of a feature `Product.md` §3.1 removed. Dynamic
social-profile scraping went for right-of-publicity, ToS and GDPR reasons, and
the same sentence named what replaces it: *"the user may paste their own text
describing the audience ('my VP hates anything that adds headcount') ... as
free-text context. User-supplied, not app-scraped."*

**Shaped, never spoken** — chosen by the architect 2026-08-21 over a room that
names it. Both were real: a panel that says *"Your VP hates headcount, so what
happens when this needs three more?"* is unmistakably responsive and lands
harder. It is also the room reciting back something the presenter typed ninety
seconds earlier, and the first thing every user then learns is that the box is a
puppet string. The tests here hold the chosen half in place from both ends: the
note reaches the prompt, and the prompt is told not to repeat it.

It is the cheapest grounding there is. Attaching a deck means having one and
waiting for extraction; one sentence about the room needs neither, and it is the
difference between a generic CFO and one who knows headcount is the fight —
which is Open Risk #2, the risk that ungrounded generic questions kill retention
faster than any UI flaw.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.agents.archetypes import by_name
from app.agents.context import Grounding, TurnContext
from app.agents.panel_models.gemini import GeminiPanelModel
from app.modules.sessions.schemas import AUDIENCE_LIMIT, EndReason

pytestmark = pytest.mark.asyncio

#: The example `Product.md` §3.1 uses, kept verbatim so the thing under test is
#: the thing the spec promised rather than a paraphrase of it.
VP = "my VP hates anything that adds headcount"


def answering(text: str):
    """A transport that returns one line and remembers what was asked for."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": text}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 7,
                },
            },
        )

    return httpx.MockTransport(handler), seen


def model_with(transport) -> GeminiPanelModel:
    return GeminiPanelModel(
        api_key="a-key-with-no-production-counterpart",
        http=httpx.AsyncClient(transport=transport),
    )


async def test_the_room_is_told_who_the_presenter_is_facing():
    """The tracer. Everything else is decoration if the note stops short of the
    request that actually asks for a question."""
    transport, seen = answering("And who signs off on three more engineers?")

    await model_with(transport).compose(
        archetype=by_name("cfo"),
        context=TurnContext(
            said="We would staff it properly.",
            grounding=Grounding(),
            audience=VP,
        ),
    )

    (request,) = seen
    assert VP in request.content.decode()


async def test_the_panel_is_told_not_to_say_it_back():
    """Option 1, and the half that has to be enforced rather than hoped for.

    Carrying the note and never constraining it is the *other* room — the one
    that recites a sentence the presenter typed a minute ago. Both halves of the
    choice are one edit apart, so the constraint needs a test or it is a comment.
    """
    transport, seen = answering("And who signs off on three more engineers?")

    await model_with(transport).compose(
        archetype=by_name("cfo"),
        context=TurnContext(
            said="We would staff it properly.", grounding=Grounding(), audience=VP
        ),
    )

    assert "Never say any of it back to them" in seen[0].content.decode()


async def test_it_is_never_offered_as_something_their_material_says():
    """A note is not a claim, and the prompt must not blur the two.

    `Grounding.claims` render under *"Their material says:"* and exist to be
    quoted — `CLAUDE.md` refuses interrogation logic that cannot cite its
    source. This came out of a text box thirty seconds ago and was never in a
    deck; a panelist attributing it to one would be inventing a provenance,
    which is exactly the failure #45 measured live.
    """
    transport, seen = answering("Where does that headcount go?")

    await model_with(transport).compose(
        archetype=by_name("cfo"),
        context=TurnContext(
            said="We would staff it properly.", grounding=Grounding(), audience=VP
        ),
    )

    body = seen[0].content.decode()
    assert VP in body
    assert "Their material says" not in body


async def test_it_may_not_become_a_fact_the_panel_states():
    """The route around #45's number rule that a free-text box opens.

    The persona forbids stating a figure the presenter did not give — and a note
    is given. But it was never *said in the room*, so the Auditor cannot check it
    and the debrief cannot rank an answer to it. A figure lifted out of this box
    would be an invented one arriving by the only door left open.
    """
    transport, seen = answering("What does that cost you?")

    await model_with(transport).compose(
        archetype=by_name("cfo"),
        context=TurnContext(
            said="We would staff it properly.", grounding=Grounding(), audience=VP
        ),
    )

    assert "Nothing in it is a fact about their business" in seen[0].content.decode()


async def test_a_room_nobody_described_is_the_room_that_shipped_before():
    """The default has to be untouched, not merely harmless.

    Most rooms will leave the box empty, and an empty one that still stamps a
    heading — or an empty fence — would change every existing room's prompt to
    say nothing. The measured behaviour in `scripts/rotation.py` and every figure
    in `docs/voice-cost.md` describes the prompt without this.
    """
    transport, seen = answering("Where does 61% come from?")
    plain = TurnContext(said="Margins are strong.", grounding=Grounding())

    await model_with(transport).compose(archetype=by_name("cfo"), context=plain)

    assert plain.audience == ""
    assert seen[0].content.decode().count('"""') == 0


# ---------------------------------------------------------------------------
# Storage. Per room, never per account and never per lineage — see below.
# ---------------------------------------------------------------------------


async def start_room(client, bearer, account, *, audience: str | None = None) -> dict:
    """One room, started over the wire, as the client would."""
    asked: dict = {"archetypes": ["cfo"], "material_ids": []}
    if audience is not None:
        asked["audience"] = audience
    response = await client.post(
        "/v1/sessions", headers=bearer(account.user_id), json=asked
    )
    assert response.status_code == 201, response.text
    return response.json()


async def settled(sessions, settlement, db, account, *, audience=None, repeats=None):
    """One finished room, so the next may start.

    Through the service rather than the endpoint, the same way
    `test_rehearsal_lineage.py` does it: a user holds one room at a time, and
    the lifecycle that enforces that already has its own suite.
    """
    session = await sessions.start(
        user_id=account.user_id, audience=audience, repeats=repeats
    )
    await sessions.activate(session_id=session.id)
    await db.commit()
    await settlement.close(session_id=session.id, end_reason=EndReason.USER_ENDED)
    return session


async def test_a_room_may_be_told_who_it_is_facing(client, bearer, funded_account):
    """The tracer for the wire. Optional, and it comes back on the room."""
    response = await client.post(
        "/v1/sessions",
        headers=bearer(funded_account.user_id),
        json={"archetypes": ["cfo"], "material_ids": [], "audience": VP},
    )

    assert response.status_code == 201
    assert response.json()["audience"] == VP


async def test_a_note_of_only_whitespace_is_no_note(client, bearer, funded_account):
    """A box somebody tabbed through described nobody.

    Stored as absent rather than as spaces, so the composer's `if
    context.audience` is answering "did they describe the room" rather than
    "is this string non-empty" — and a fence containing three spaces never
    reaches a prompt.
    """
    response = await client.post(
        "/v1/sessions",
        headers=bearer(funded_account.user_id),
        json={"archetypes": ["cfo"], "material_ids": [], "audience": "   "},
    )

    assert response.json()["audience"] is None


async def test_a_note_longer_than_a_paragraph_is_refused(
    client, bearer, funded_account
):
    """Refused at 422, never truncated, and the cap is part of the fencing.

    `PERSONA_LIMIT` settled the same question one field over: *"a paragraph
    describes somebody, and a page is room to argue with the instructions
    underneath it."* Truncating would also store something other than what was
    typed, which `rehearsal_name` already refuses to do.
    """
    response = await client.post(
        "/v1/sessions",
        headers=bearer(funded_account.user_id),
        json={
            "archetypes": ["cfo"],
            "material_ids": [],
            "audience": "x" * (AUDIENCE_LIMIT + 1),
        },
    )

    assert response.status_code == 422


async def test_a_second_room_does_not_inherit_the_first_ones_audience(
    client, db, bearer, sessions, settlement, funded_account
):
    """**The constraint that decided where this lives.**

    `rehearsal_name` belongs to the *lineage* and is inherited: the newest name
    in a group is the group's. This is not, and must not be. Somebody can
    rehearse one argument for their VP on Monday and for the board on Friday,
    and those are two attempts at the same thing — one lineage, two rooms.
    Lineage inheritance would put Monday's note silently into Friday's room.

    So it is per room. A re-run still gets it back without retyping, because
    the setup screen prefills from the room being repeated — inherited where
    somebody can see and change it, never behind their back.
    """
    await settled(sessions, settlement, db, funded_account, audience=VP)

    fresh = await start_room(client, bearer, funded_account)

    assert fresh["audience"] is None


async def test_a_finished_room_still_reports_what_it_was_told(
    client, db, bearer, sessions, settlement, funded_account
):
    """Where "Run it again" prefills from.

    Per-room storage only avoids the retype problem if the room can be read
    back. The Library already lists finished rooms; this is what puts the note
    in the box beside the panel and the deck, where somebody can change it
    before Start rather than discover it afterwards.
    """
    await settled(sessions, settlement, db, funded_account, audience=VP)

    rooms = (
        await client.get("/v1/sessions", headers=bearer(funded_account.user_id))
    ).json()

    assert [room["audience"] for room in rooms] == [VP]


async def test_the_note_is_not_copied_into_the_audit_trail(
    client, db, bearer, funded_account
):
    """`audit_events` is append-only, so anything written there is permanent.

    A note names colleagues — "my VP", "the CFO who blocked this last time" —
    which is the class `CLAUDE.md` forbids logging, and the audit table is the
    one place a mistake cannot be edited back out. The start event records that
    a room opened and what it was grounded in; it does not record this.
    """
    from app.modules.audit_log.models import AuditEvent

    await start_room(client, bearer, funded_account, audience=VP)

    events = (await db.scalars(select(AuditEvent))).all()

    assert events
    assert not any(VP in str(event.context) for event in events)


# ---------------------------------------------------------------------------
# The wiring. A stored note nothing reads is a box that does nothing.
# ---------------------------------------------------------------------------


class FakeTranscriber:
    def open(self):  # pragma: no cover - never dialled here
        raise NotImplementedError


class FakePanelModel:
    async def select(self, *, candidates, context):  # pragma: no cover
        raise NotImplementedError

    async def compose(self, *, archetype, context, finding=None, dispute=None):  # pragma: no cover
        raise NotImplementedError


async def test_the_room_is_built_knowing_who_it_is_facing(db, funded_account):
    """The other end of the trip, and the half that is easy to leave out.

    The note is stored at start and read by the composer; between those two
    sits `build_room`, which is the only thing that turns a session id into
    something a socket holds. A column nothing loads is a text box that does
    nothing, and it would fail silently — the room still opens, still asks
    questions, and is simply the generic one.

    Public on the provider for the reason `panel` and `pressure` are: it is a
    fact about the room rather than an implementation detail, and it is what a
    caller checks to know which room it got.
    """
    from app.modules.sessions.service import SessionService
    from app.modules.voice.room import build_room

    session = await SessionService(db).start(
        user_id=funded_account.user_id, audience=VP
    )

    room = await build_room(
        db,
        session_id=session.id,
        user_id=funded_account.user_id,
        transcriber=FakeTranscriber(),
        model=FakePanelModel(),
    )

    assert room.audience == VP


async def test_a_room_nobody_described_carries_no_note(db, funded_account):
    """Null in the column becomes the empty string, not the string "None".

    `TurnContext.audience` is a `str` because the composer branches on
    truthiness and a `str | None` would put that branch one `is not None` away
    from rendering a fence around the word None. The conversion belongs here,
    at the one crossing, rather than in three prompt builders.
    """
    from app.modules.sessions.service import SessionService
    from app.modules.voice.room import build_room

    session = await SessionService(db).start(user_id=funded_account.user_id)

    room = await build_room(
        db,
        session_id=session.id,
        user_id=funded_account.user_id,
        transcriber=FakeTranscriber(),
        model=FakePanelModel(),
    )

    assert room.audience == ""
