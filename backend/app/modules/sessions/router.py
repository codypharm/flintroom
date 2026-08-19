"""Session endpoints.

Thin, per `CLAUDE.md`: parse the request, call a service, return a response.
"""

import base64
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.core.errors import ClipTooLong, RecordingNotAvailable
from app.core.storage_s3 import DEFAULT_EXPIRY_SECONDS
from app.modules.auth.dependencies import CurrentUser, rate_limit_user
from app.modules.ingestion.dependencies import ObjectStorageDep
from app.modules.voice.recording import recording_key
from app.modules.auth.rate_limit import OPENING_REPLAY_LIMIT, SESSION_START_LIMIT
from app.modules.sessions.dependencies import (
    CoachServiceDep,
    DebriefServiceDep,
    PreferenceServiceDep,
    RecordingRetentionDep,
    OwnedSession,
    SessionServiceDep,
    SettlementServiceDep,
)
from app.modules.sessions.schemas import (
    CoachTurnRead,
    DebriefRead,
    RecordingPreference,
    RecordingPreferenceUpdate,
    RecordingPlayback,
    RecordingState,
    EndReason,
    SessionRead,
    SessionStart,
    SessionStarted,
    WeakAnswerRead,
)
from app.modules.voice.dependencies import VoiceTicketServiceDep

#: The most a single spoken turn may weigh.
#:
#: Ten megabytes is roughly five minutes of PCM16 at 16 kHz, and far more of
#: anything a phone actually records — so it bounds abuse without ever being
#: reached by somebody answering a question. Generous on purpose: the failure of
#: a limit set too tight is a user whose longest, most considered answer is the
#: one that gets refused.
MAX_CLIP_BYTES = 10 * 1024 * 1024

router = APIRouter(tags=["sessions"])


@router.post(
    "/sessions",
    response_model=SessionStarted,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_user("session_start", SESSION_START_LIMIT))],
)
async def start_session(
    user_id: CurrentUser,
    sessions: SessionServiceDep,
    tickets: VoiceTicketServiceDep,
    body: SessionStart | None = None,
) -> SessionStarted:
    """Open a room for the caller, and hand them the key to its stream.

    The user is taken from the credential, never from the body: a client that
    could name the account would be able to spend somebody else's minutes.

    Two service calls rather than one, and still no rules here — the sequence
    carries no branch and no condition, so nothing about *when* a room may open
    has leaked out of `SessionService`. If the mint ever grows a decision, it
    belongs behind a service of its own, as settlement did for the join between
    sessions and the ledger.

    A mint that failed after the start committed would leave the caller holding
    a room they cannot connect to and unable to open another until the reaper
    clears it, roughly a minute later. Both statements run on the same
    connection against the same database, so the case is nearly always "the
    database is gone", where the start would not have committed either.
    """
    session = await sessions.start(
        user_id=user_id,
        material_ids=body.material_ids if body else [],
        archetypes=body.archetypes if body else [],
    )
    return SessionStarted(
        **(await _read(session, sessions)).model_dump(),
        stream_ticket=await tickets.mint(session_id=session.id, user_id=user_id),
    )


@router.get("/sessions", response_model=list[SessionRead])
async def list_sessions(
    user_id: CurrentUser, sessions: SessionServiceDep
) -> list[SessionRead]:
    """This account's rooms, newest first.

    Scoped by the caller's own id, never by a query parameter. A list endpoint
    that took a user id would be an authorisation check waiting to be forgotten.

    Carries no transcript and no audio — `CLAUDE.md` keeps both out of list
    responses — only whether each room can still be heard, and until when.
    """
    return await sessions.recent(user_id=user_id)


@router.get("/sessions/{session_id}", response_model=SessionRead)
async def read_session(
    session: OwnedSession, sessions: SessionServiceDep
) -> SessionRead:
    """One session, if it belongs to the caller."""
    return await _read(session, sessions)


@router.get("/preferences/recording", response_model=RecordingPreference)
async def read_recording_preference(
    user_id: CurrentUser, preferences: PreferenceServiceDep
) -> RecordingPreference:
    """Whether rooms are being saved for this account."""
    return RecordingPreference(
        records_rooms=await preferences.records_rooms(user_id=user_id),
        retention_days=await preferences.retention_days(user_id=user_id),
    )


@router.put("/preferences/recording", response_model=RecordingPreference)
async def set_recording_preference(
    body: RecordingPreferenceUpdate,
    user_id: CurrentUser,
    preferences: PreferenceServiceDep,
) -> RecordingPreference:
    """Turn saving on or off for future rooms.

    `PUT` rather than `POST`, because this sets a value rather than appending
    one — the second identical request is the same state, which is exactly what
    a toggle tapped twice on a slow connection produces.

    Affects rooms started after this. Existing recordings are deliberately left
    alone: they were made under a disclosure the user accepted, and destroying
    them as a side effect of a switch would be a surprise in the one direction
    that cannot be undone. Deleting a room is its own explicit action, below.
    """
    await preferences.set_records_rooms(
        user_id=user_id, enabled=body.records_rooms
    )
    return RecordingPreference(
        records_rooms=body.records_rooms,
        retention_days=await preferences.retention_days(user_id=user_id),
    )


@router.delete(
    "/sessions/{session_id}/recording", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_recording(
    session: OwnedSession, retention: RecordingRetentionDep
) -> None:
    """Destroy one room's audio, because the user asked.

    204 whether or not there was anything there. `CLAUDE.md` lists duplicate
    actions as a case to handle rather than a 500, and a second tap is asking
    for something already true — answering 404 would tell somebody their
    deletion failed at the moment it had in fact succeeded.

    The transcript survives. The two artefacts have separate lifetimes by
    design, and this must not quietly take the debrief's grounding with it.
    """
    await retention.delete(session_id=session.id)


@router.get(
    "/sessions/{session_id}/recording", response_model=RecordingPlayback
)
async def play_recording(
    session: OwnedSession,
    sessions: SessionServiceDep,
    storage: ObjectStorageDep,
) -> RecordingPlayback:
    """A link to hear one room again.

    Plays the stored object. ElevenLabs is never called and no credits are
    consumed — re-synthesising a room costs about a hundred times what storing
    it does, and could not reproduce the user's own voice at any price.

    Ownership is settled by `OwnedSession` before this body runs, and the
    recording's state is checked before a URL is asked for. `core/storage.py`
    says why that order matters: signing is not a permission check, and that
    layer signs whatever it is told to sign.

    Refuses rather than signing a key that is not there. A URL to an absent
    object is a link that reaches the store, fails there, and leaves the client
    reading somebody else's error page — and the state is already published on
    the session, so a well-behaved client never arrives here at all.
    """
    recording = await sessions.recording(session_id=session.id)
    if recording.state is not RecordingState.AVAILABLE:
        raise RecordingNotAvailable(
            context={"session_id": str(session.id), "state": recording.state.value}
        )

    return RecordingPlayback(
        url=storage.presign_get(recording_key(session.id)),
        expires_in_seconds=DEFAULT_EXPIRY_SECONDS,
    )


@router.post("/sessions/{session_id}/end", response_model=SessionRead)
async def end_session(
    session: OwnedSession,
    settlement: SettlementServiceDep,
    sessions: SessionServiceDep,
) -> SessionRead:
    """The End button: an intent, honoured by the server.

    The end reason is not taken from the body. `user_ended` is the only ending
    a client is in a position to report, and every other reason in the enum
    decides whether minutes are refunded — a client that could name one would
    be choosing its own refund.
    """
    return await _read(
        await settlement.close(session_id=session.id, end_reason=EndReason.USER_ENDED),
        sessions,
    )


async def _read(session, sessions: SessionServiceDep) -> SessionRead:
    """A session with the grounding it was started against, and the room in it.

    Two extra queries rather than eager relationships on `Session`. The sweeps
    that run every fifteen seconds select columns instead of rows, so they would
    not pay for it — but `_active_session` does load a row, on every single
    start, to answer a question that has nothing to do with either. Paying there
    for something only three responses read is the wrong place to spend it.

    Assembly, not a rule: no branch, no condition, nothing about *what* may
    ground a room or sit in it has leaked out of `SessionService`.
    """
    panel = await sessions.panel(session_id=session.id)
    return SessionRead.model_validate(session).model_copy(
        update={
            "material_ids": await sessions.materials(session_id=session.id),
            "recording": await sessions.recording(session_id=session.id),
            "archetypes": [archetype.name for archetype in panel],
        }
    )


@router.get("/sessions/{session_id}/debrief", response_model=DebriefRead)
async def read_debrief(
    session: OwnedSession,
    debrief: DebriefServiceDep,
    coaching: CoachServiceDep,
) -> DebriefRead:
    """What went badly in this room, worst first.

    The first open reads the room with a reasoning model and stores the result;
    every open after hands back what was stored. That matters on a phone, where
    backgrounding and resuming re-fetches: a recomputed list would cost a second
    model call *and* reshuffle, because the ranking moves between runs on the
    same transcript.

    `OwnedSession` settles who is asking before this body runs, which is more
    than routine here — a transcript is the most private thing the product
    holds, kept for the life of the account precisely so the debrief can read
    it. A 403 returned after the model had read the room would still have read
    the room.

    Three rooms are refused rather than debriefed, each as a typed error a
    client can act on: one still running, one where the panel never asked
    anything, and one the provider broke — which offers a fresh room, because
    the minutes are already back.
    """
    # Computed before the list is drawn, and this reads oddly until the cost is
    # in view. The coach reads the ranked answers to write its opening, and
    # `CoachService.open` gets them through `DebriefService` — the same
    # idempotent call `debrief.weak_answers` below makes, returning the stored
    # list without a second model call. So the order costs nothing and buys the
    # guarantee that a client which draws the sheet has already been greeted.
    opening = await coaching.open(session_id=session.id)

    return DebriefRead(
        opening=(
            CoachTurnRead(
                text=opening.text,
                speech=base64.b64encode(opening.speech).decode(),
                heard=opening.heard,
            )
            if opening is not None
            else None
        ),
        weak_answers=[
            WeakAnswerRead(
                ordinal=answer.ordinal,
                question=answer.question,
                asked_by=answer.asked_by,
                answer=answer.answer,
                weakness=answer.weakness.value,
                why=answer.why,
            )
            for answer in await debrief.weak_answers(session_id=session.id)
        ],
        # Read after the weak answers, not before, and the order is the whole
        # of it: reading them is what moves the rung, so a comparison taken
        # first would describe the world one calibration out of date.
        pressed=await debrief.pressed(session_id=session.id),
    )


@router.post(
    "/sessions/{session_id}/debrief/opening/speech",
    response_model=CoachTurnRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_user("debrief_opening", OPENING_REPLAY_LIMIT))],
)
async def say_the_opening_again(
    session: OwnedSession,
    coaching: CoachServiceDep,
) -> CoachTurnRead:
    """Hear the greeting again.

    The opening speaks itself on arrival and comes back silent on every read
    after, because `docs/voice-cost.md` puts the expressive speaker at about
    $0.0002 a character — a spoken greeting costs roughly a minute of live
    interrogation, and the debrief read is what a backgrounded phone repeats.
    This is where that cost is paid instead: once, when somebody asks.

    `POST` rather than `GET`, and not for style. It is not safe and it is not
    cacheable: every call pays a synthesis vendor, and a proxy or a client
    library that retried a `GET` for free would be spending money it thought was
    idempotent.

    Rate-limited for the same reason. This is the only endpoint in the product
    where one authenticated user can spend a vendor at will, and no honest
    client presses replay in a loop.

    Unmetered, like every coaching turn — there is no path from here to a
    balance.
    """
    turn = await coaching.say_the_opening_again(session_id=session.id)

    return CoachTurnRead(
        text=turn.text,
        speech=base64.b64encode(turn.speech).decode(),
        heard=turn.heard,
    )


@router.post(
    "/sessions/{session_id}/debrief/turns",
    response_model=CoachTurnRead,
    status_code=status.HTTP_201_CREATED,
)
async def speak_to_coach(
    session: OwnedSession,
    coaching: CoachServiceDep,
    clip: Annotated[UploadFile, File(description="One recorded turn.")],
) -> CoachTurnRead:
    """Say one thing to the coach, and hear one thing back.

    One turn per request rather than a socket. `docs/debrief-and-sparring.md`
    decision 5: hands-free is a property of the *interrogation*, so the debrief
    has no barge-in to support and nothing to overlap, and a held socket would
    bill for silence on an unmetered phase — the failure `IDLE_LIMIT` exists to
    catch in the room.

    Not "push-to-talk", which that decision said and its 2026-08-18 amendment
    withdrew. The argument was always about transport; how the client starts and
    stops recording is a separate choice, and the shipped one is tap-to-start,
    tap-to-stop.

    Unmetered, and no ticket. Nothing about this call touches the ledger, which
    is the metering boundary being structural rather than remembered: there is
    no code path from here to a balance.

    The reply carries text as well as audio. That is the accessibility floor
    `CLAUDE.md` sets — WCAG 2.2 AA plus live captions, as a v1 requirement — and
    a client cannot caption bytes it was handed.
    """
    # Read with one byte of headroom so a clip exactly at the ceiling passes and
    # anything past it is caught here rather than by however much memory the
    # process had left. `UploadFile` spools to disk above a threshold, so this
    # bounds what reaches the transcriber rather than what reaches the process —
    # which is the number that matters, since the vendor is billed by audio.
    recorded = await clip.read(MAX_CLIP_BYTES + 1)
    if len(recorded) > MAX_CLIP_BYTES:
        raise ClipTooLong(
            session_id=str(session.id), limit_bytes=MAX_CLIP_BYTES
        )

    turn = await coaching.say(
        session_id=session.id,
        clip=recorded,
        media_type=clip.content_type or "application/octet-stream",
    )

    return CoachTurnRead(
        text=turn.text,
        speech=base64.b64encode(turn.speech).decode(),
        heard=turn.heard,
    )


@router.post(
    "/sessions/{session_id}/debrief/weak-answers/{rank}/attempts",
    response_model=CoachTurnRead,
    status_code=status.HTTP_201_CREATED,
)
async def spar(
    session: OwnedSession,
    rank: int,
    coaching: CoachServiceDep,
    clip: Annotated[UploadFile, File(description="One re-answer, spoken.")],
) -> CoachTurnRead:
    """Answer one of the room's questions again, and hear what changed.

    §3.5's re-try loop: *"the coach replays a question the user fumbled and has
    them re-answer on the spot, repeatedly, until the response holds. Teaching,
    not just scoring."*

    **The question is in the path, not in the body.** That is
    `docs/debrief-and-sparring.md` decision 4's anchor, and it is required
    rather than conventional: a re-answer is fresh speech about the session,
    which is precisely the shape *"spar me on this instead"* would use to
    smuggle in a new pitch. Addressing a stored rank means there is no argument
    in which a different subject could be named.

    Nothing here announces a verdict. The coach says what changed between this
    attempt and the last; the user decides when to stop. Telling somebody a thin
    answer landed sends them into the real room believing it, which is the one
    outcome this loop exists to prevent.

    Unmetered, like every coaching turn, and with no path from here to a
    balance.
    """
    recorded = await clip.read(MAX_CLIP_BYTES + 1)
    if len(recorded) > MAX_CLIP_BYTES:
        raise ClipTooLong(session_id=str(session.id), limit_bytes=MAX_CLIP_BYTES)

    turn = await coaching.spar(
        session_id=session.id,
        weak_rank=rank,
        clip=recorded,
        media_type=clip.content_type or "application/octet-stream",
    )

    return CoachTurnRead(
        text=turn.text,
        speech=base64.b64encode(turn.speech).decode(),
        heard=turn.heard,
    )
