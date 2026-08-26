"""Speaking to the coach, over HTTP.

`CoachService` is exercised directly in `test_coaching.py`. What these add is
what the transport introduces: who is calling, whether they own the room, and
the one upload this API proxies rather than presigning.
"""

from __future__ import annotations

import base64

from app.agents.coach import Cite, CoachReply
from app.agents.context import USER, Said
from app.agents.model import TurnUsage
from app.agents.weakness import Judgement, Weakness
from app.modules.sessions.router import MAX_CLIP_BYTES

from tests.conftest import create_funded_account
from tests.test_debrief import room_that_happened

ROOM = (
    Said(speaker=USER, text="We grew forty percent last quarter."),
    Said(speaker="cfo", text="Off what base, and at what cost?"),
    Said(speaker=USER, text="We are really pleased with the trajectory."),
)

FOUND = Judgement(
    ordinal=1,
    quote="Off what base, and at what cost?",
    weakness=Weakness.EVASIVE,
    why="You answered with a feeling about the trend, not a base.",
)

# The bytes and nothing else. Multipart until 2026-08-20, which a raw-body
# handler would swallow whole — the MIME envelope reaching the transcriber as
# though it were audio, with every assertion here still green.
CLIP = b"a recording"
WAV = {"Content-Type": "audio/wav"}


def sse_events(body: str) -> list[tuple[str, str]]:
    """Each (event, data) frame, in arrival order."""
    frames = []
    for block in body.strip().split("\n\n"):
        event, data = None, ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data = line[len("data: "):]
        if event:
            frames.append((event, data))
    return frames


async def test_a_streamed_turn_ships_the_words_before_the_voice(
    client, db, engine, sessions, settlement, funded_account, bearer,
    weakness_reader, coach_model, speaker,
):
    """#107 item 1: the words the moment the fence passes, the audio as frames.

    The old shape held the text hostage to the whole synthesis — captions and
    speech arrived together, after the slowest step. Here the order IS the
    contract: heard, then text, then each speech frame as the vendor produces
    it, then done. The frames joined are byte-identical to what the JSON
    endpoint would have returned, so nothing about what is eventually heard
    changed — only when the screen can start showing something.
    """
    import base64
    import json

    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    weakness_reader.judged = (FOUND,)
    coach_model.reply_with = CoachReply(
        text="The CFO wanted a base. You gave a mood.",
        cites=(Cite(kind="line", index=1),),
        usage=TurnUsage(900, 120),
    )

    response = await client.post(
        f"/v1/sessions/{session.id}/debrief/turns/stream",
        headers={**bearer(funded_account.user_id), **WAV},
        content=CLIP,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    frames = sse_events(response.text)
    names = [event for event, _ in frames]
    assert names[0] == "heard"
    assert names[1] == "text"
    assert names[-1] == "done"
    assert names[2:-1] and all(name == "speech" for name in names[2:-1])

    assert json.loads(frames[1][1])["text"] == "The CFO wanted a base. You gave a mood."
    voiced = b"".join(
        base64.b64decode(json.loads(data)["b64"])
        for event, data in frames
        if event == "speech"
    )
    assert voiced == b"\x01\x02\x03\x04"


async def test_a_streamed_turn_still_refuses_a_stranger(
    client, db, engine, sessions, settlement, funded_account, bearer, ledger,
):
    """The stream is the same door with the same lock."""
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    stranger = await create_funded_account(db, ledger)

    response = await client.post(
        f"/v1/sessions/{session.id}/debrief/turns/stream",
        headers={**bearer(stranger.user_id), **WAV},
        content=CLIP,
    )

    assert response.status_code == 404


async def test_a_spoken_turn_comes_back_as_captions_and_audio(
    client, db, engine, sessions, settlement, funded_account, bearer,
    weakness_reader, coach_model, speaker,
):
    """The tracer, and the accessibility floor in the response shape.

    `CLAUDE.md` puts WCAG 2.2 AA *plus live captions* in v1 rather than after
    it, so the text is not a debug field — it is how part of the audience uses
    the product at all. A client cannot caption bytes it was handed.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    weakness_reader.judged = (FOUND,)
    coach_model.reply_with = CoachReply(
        text="The CFO wanted a base. You gave a mood.",
        cites=(Cite(kind="line", index=1),),
        usage=TurnUsage(900, 120),
    )

    response = await client.post(
        f"/v1/sessions/{session.id}/debrief/turns",
        headers={**bearer(funded_account.user_id), **WAV},
        content=CLIP,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["text"] == "The CFO wanted a base. You gave a mood."
    assert base64.b64decode(body["speech"]) == b"\x01\x02\x03\x04"


async def test_somebody_elses_room_cannot_be_spoken_to(
    client, db, engine, sessions, settlement, funded_account, bearer, ledger,
    weakness_reader, coach_model,
):
    """Ownership before anything is heard.

    Sharper than a read: this endpoint would otherwise transcribe a stranger's
    audio *and* hand back the contents of somebody else's rehearsal in the
    coach's answer. Asserted on the coach never being asked, because a 404
    returned afterwards would still have done both.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    stranger = await create_funded_account(db, ledger)

    response = await client.post(
        f"/v1/sessions/{session.id}/debrief/turns",
        headers=bearer(stranger.user_id),
        content=CLIP,
    )

    assert response.status_code == 404
    assert coach_model.saw_grounds is None


async def test_a_clip_past_the_ceiling_is_refused(
    client, db, engine, sessions, settlement, funded_account, bearer,
    weakness_reader, coach_model, dictation,
):
    """The ceiling the dependency justification promised.

    This is the one upload the API proxies — decks go straight to object storage
    by presigned URL and never enter the process. Proxying is right for a few
    seconds of speech that is heard and dropped, and it is a memory-exhaustion
    endpoint without a bound.

    Asserted on the transcriber never being called: refusing after paying a
    vendor to hear ten megabytes would refuse the request and buy the abuse.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )

    response = await client.post(
        f"/v1/sessions/{session.id}/debrief/turns",
        headers={**bearer(funded_account.user_id), **WAV},
        content=b"x" * (MAX_CLIP_BYTES + 1),
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "clip_too_long"
    assert dictation.heard == []


async def test_speaking_without_a_credential_transcribes_nothing(
    client, db, engine, sessions, settlement, funded_account, dictation,
):
    """An unauthenticated POST must not reach a paid vendor.

    Every model call on this path is money, on a phase that earns none. An
    endpoint that transcribed first and checked afterwards would be an invoice
    anybody on the internet could generate.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )

    response = await client.post(
        f"/v1/sessions/{session.id}/debrief/turns", content=CLIP
    )

    assert response.status_code == 401
    assert dictation.heard == []


async def test_the_reply_carries_back_what_the_transcriber_heard(
    client, db, engine, sessions, settlement, funded_account, bearer,
    weakness_reader, coach_model, speaker, dictation,
):
    """The user's own words, returned to the user who said them.

    Two things need this and neither is cosmetic.

    A dictated turn is the one place in the product where a vendor's mistake is
    invisible: if the transcriber hears "twelve" for "twelve hundred", the coach
    answers the sentence it was given and the reply reads as though the coach
    stopped listening. Showing what was heard is the only way somebody can tell
    a coaching disagreement from a transcription error.

    The debrief screen also needs it structurally. A re-answer is stored in
    `SparringAttempt.said` and was never sent anywhere, so a client could show
    what the room got and what the coach replied, with the answer that changed
    between them missing from the middle.

    Not a `CLAUDE.md` list-endpoint disclosure: this is one turn, returned to
    its owner, in the response to their own speech.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    weakness_reader.judged = (FOUND,)
    dictation._text = "We grew off a base of two million."

    response = await client.post(
        f"/v1/sessions/{session.id}/debrief/turns",
        headers={**bearer(funded_account.user_id), **WAV},
        content=CLIP,
    )

    assert response.status_code == 201
    assert response.json()["heard"] == "We grew off a base of two million."


async def test_a_re_answer_comes_back_beside_what_was_heard(
    client, db, engine, sessions, settlement, funded_account, bearer,
    weakness_reader, coach_model, speaker, dictation,
):
    """Sparring, where the stored attempt makes the omission plainest.

    `CoachService.spar` already writes `said` to the row and hands the caller
    only the reply. The sheet that shows a first answer against a second cannot
    be built from that, and reconstructing it on the client would mean the app
    transcribing speech the server has already paid to transcribe.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    weakness_reader.judged = (FOUND,)
    dictation._text = "Off a base of two million, at a cost of forty a customer."

    response = await client.post(
        f"/v1/sessions/{session.id}/debrief/weak-answers/0/attempts",
        headers={**bearer(funded_account.user_id), **WAV},
        content=CLIP,
    )

    assert response.status_code == 201
    assert (
        response.json()["heard"]
        == "Off a base of two million, at a cost of forty a customer."
    )


async def test_a_turn_is_the_wav_itself_rather_than_a_form_around_it(
    client, db, engine, sessions, settlement, funded_account, bearer,
    weakness_reader, coach_model, speaker,
):
    """One clip, sent as the body, with nothing wrapped around it.

    Multipart carries several parts and this request has one — the session is
    already in the path, so the envelope has nothing left to hold. Deepgram and
    AssemblyAI take the same shape for the same job.

    What forces it rather than merely favouring it is the client. The recorder
    hands React Native in-memory PCM and never a file URI, and `BlobManager`
    throws on an `ArrayBuffer` outright, so there is no multipart part a phone
    can build from what it is holding — short of writing the user's voice to
    disk purely to satisfy the envelope. Until 2026-08-20 the app tried anyway
    and threw before opening a socket, which somebody read as "I could not reach
    the server" on a server that had never been called.
    """
    session = await room_that_happened(
        db, engine, sessions, settlement, funded_account, *ROOM
    )
    weakness_reader.judged = (FOUND,)
    coach_model.reply_with = CoachReply(
        text="Lead with the number.",
        cites=(Cite(kind="line", index=1),),
        usage=TurnUsage(900, 120),
    )

    response = await client.post(
        f"/v1/sessions/{session.id}/debrief/turns",
        headers={**bearer(funded_account.user_id), "Content-Type": "audio/wav"},
        content=b"a recording",
    )

    assert response.status_code == 201
    assert response.json()["text"] == "Lead with the number."
