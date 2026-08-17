"""Session states and read models.

The state machine is specified in `docs/minutes-ledger-and-sessions.md` Part 2.
"""

import uuid
from datetime import datetime, timedelta
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

#: How often a live interrogation is billed — and, because the tick doubles as
#: the heartbeat, how often the client proves it is still there. Declared here
#: rather than in the tick loop because the reaper needs it too, and "how long
#: is three missed ticks" must not be able to disagree with "how long is a
#: tick" (docs/minutes-ledger-and-sessions.md Part 2, Detection).
TICK_INTERVAL = timedelta(seconds=15)

#: How long a session may keep running past a zero balance before the room is
#: closed. Product.md §4.5 forbids interrupting a live interrogation, so the
#: alternative to a bound is not "cut them off sooner" — it is a room that runs
#: on our invoice until someone notices. Two minutes is what the grace write-off
#: was costed against (docs Part 1, Zero mid-session); moving it moves that
#: number, which is a pricing change and therefore not ours to make.
GRACE_LIMIT = timedelta(seconds=120)

#: How long one interrogation may run before the room closes itself. A bound on
#: a forgotten room rather than a promise about session length: a user with
#: minutes in the bank has nothing in their balance that would ever stop them,
#: and a phone left face-down after the panel finished would otherwise burn
#: provider time against an empty room until the balance ran out.
SESSION_LIMIT = timedelta(minutes=12)

#: How long the user may say nothing before the room is treated as abandoned.
#: Only *user* speech resets it — a panel talking to an empty room is the
#: expensive failure this exists to catch, not evidence that anyone is there.
#: Long enough to sit through a hostile question and think before answering,
#: which is the behaviour the product is asking for.
IDLE_LIMIT = timedelta(seconds=90)


class SessionState(str, Enum):
    """The five states a session can be in.

    ```
    provisioning ──► active ──► finalizing ──► settled
         │
         └──► failed
    ```

    `provisioning` and `failed` exist because ElevenLabs agent spin-up takes
    real time and can fail before any audio exists. Without them a spin-up
    failure is indistinguishable from a real session in every query and every
    cost report.

    `finalizing` exists because settlement must be crash-safe: without it,
    nothing separates "finished settling" from "died halfway," and the reaper
    cannot safely retry.
    """

    PROVISIONING = "provisioning"
    ACTIVE = "active"
    FINALIZING = "finalizing"
    SETTLED = "settled"
    FAILED = "failed"


class SessionPhase(str, Enum):
    """What the user is doing inside a session.

    The metering boundary in one place (Product.md §4.1, CLAUDE.md → Metering
    Rules): `INTERROGATION` is billable, the two coaching phases are not. Making
    it a phase rather than a flag on the ledger write means a new unmetered
    phase cannot accidentally start charging — it would have to be added to the
    billable set deliberately.
    """

    INTERROGATION = "interrogation"
    DEBRIEF = "debrief"
    SPARRING = "sparring"


#: The only phase that costs the user minutes. Everything after the room closes
#: is unmetered and stays that way — see CLAUDE.md → Metering Rules.
METERED_PHASES = frozenset({SessionPhase.INTERROGATION})


class EndReason(str, Enum):
    """Why a session stopped.

    Recorded because these are not equivalent to the business: a session that
    ended because the user was finished is a success, and one that ended on a
    provider failure is a refund and an incident. Both look identical in the
    ledger without this.
    """

    #: The user pressed End. An intent, honoured by the server.
    USER_ENDED = "user_ended"

    #: The per-session interrogation cap. Protects against a forgotten room.
    SESSION_CAP = "session_cap"

    #: The bounded grace overdraft ran out, past a zero balance.
    GRACE_CAP = "grace_cap"

    #: No *user* speech while the panel awaited an answer. Panel speech does
    #: not count — an agent monologuing to an empty room is the expensive
    #: failure this exists to catch.
    IDLE_TIMEOUT = "idle_timeout"

    #: The voice provider failed mid-session. The affected minutes are refunded.
    PROVIDER_FAILURE = "provider_failure"

    #: Three missed ticks, roughly 45 seconds. Arrears ticking means the ledger
    #: is already correct and no refund is owed.
    CLIENT_DISCONNECT = "client_disconnect"

    #: Agent spin-up never completed. Nothing was billed; this ends in `failed`,
    #: not `settled`.
    PROVISIONING_FAILED = "provisioning_failed"


#: How many materials one room may be grounded in.
#:
#: A guard rather than a considered limit, and the real bound is elsewhere: what
#: the Auditor can hold is claims, not files, and a single pro-tier deck already
#: carries more of those than a context window wants. Whatever replaces this
#: will be counted in claims and will belong with the panel work.
#:
#: Ten is comfortably above the shape the product expects — a deck, perhaps an
#: appendix, perhaps a photograph of the whiteboard — and low enough that
#: nobody attaches a library by accident or on purpose.
MAX_SESSION_MATERIALS = 10

#: How many archetype names one request may carry.
#:
#: **An abuse guard, not the product limit.** The real cap is the caller's tier
#: (`billing/tiers.py` → `MAX_PANEL_SIZE`), and it has to be, because only the
#: service knows which plan the caller is on. Setting this to the largest tier's
#: seats would look tidier and behave worse: a Pro user asking for six would be
#: refused by Pydantic with a generic length error instead of by `PanelTooLarge`
#: with the sentence that names their plan's number.
#:
#: So it sits well above every tier, exactly as `MAX_SESSION_MATERIALS` does —
#: high enough that every refusal a real user meets is the one that explains
#: itself, low enough that nobody posts a list of ten thousand names.
MAX_REQUESTED_PANELISTS = 25


class SessionStart(BaseModel):
    """What a room may be configured with: its grounding, and who is in it.

    Extra fields are refused rather than ignored. A client sending `materialIds`
    in camelCase should be told, not silently given an ungrounded room — which
    is the failure that looks exactly like the panel being bad at its job.
    """

    model_config = ConfigDict(extra="forbid")

    #: Optional, and the empty case is first-class rather than degraded.
    #: `docs/auditor-grounding.md` gives the deckless panel abundant material to
    #: attack, so a user who does not want to wait for extraction starts without
    #: a deck instead of being blocked.
    material_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=MAX_SESSION_MATERIALS
    )

    #: Archetype names, in the order they should be seated. Empty means the
    #: shipped mixed default — a champion, a skeptic and a neutral — rather than
    #: an empty room, on the same reasoning as material above.
    #:
    #: Order is carried through rather than sorted. `routing.choose` breaks a
    #: scoring tie on the panel's own index, so the seat a user gives an
    #: archetype is a real input to who speaks.
    archetypes: list[str] = Field(
        default_factory=list, max_length=MAX_REQUESTED_PANELISTS
    )


class RecordingState(str, Enum):
    """Whether a room can still be heard, and if not, why not.

    Three states rather than a nullable URL, because two of them are ordinary
    and mean different things to the person reading the screen. "No longer
    available" is a retention window arriving exactly on schedule; "not
    recorded" is saving having been off. Telling somebody the first when the
    second is true reads as data loss.
    """

    #: There is an object, and a URL can be minted for it.
    AVAILABLE = "available"
    #: There was one, and the retention sweep removed it on schedule.
    EXPIRED = "expired"
    #: There never was one — saving was off, the room failed, or nothing was said.
    NOT_RECORDED = "not_recorded"


class RecordingRead(BaseModel):
    """What a client is told about a room's audio, without minting anything.

    Carries no URL. A presigned link lives fifteen minutes and a session object
    can be cached, re-rendered or scrolled past for much longer, so embedding
    one here would hand out links that are dead by the time anybody presses
    play. The URL is minted by its own endpoint, at the moment it is wanted.
    """

    model_config = ConfigDict(from_attributes=True)

    state: RecordingState

    #: When the audio stops being playable, or null when there is none.
    #:
    #: Published deliberately. The window is a promise on a tier card, and a
    #: client that knows the date can say "available until March" instead of
    #: leaving somebody to discover the answer by coming back too late.
    expires_at: datetime | None = None


class RecordingPreference(BaseModel):
    """Whether this account's rooms are recorded.

    One field, and it is the control the first-session disclosure points at.
    `docs/session-retention.md` chose on-by-default with a way out; this is the
    way out, and without it the disclosure would be describing something that
    does not exist.
    """

    records_rooms: bool


class RecordingPlayback(BaseModel):
    """A short-lived link to one room's audio.

    Minted on demand rather than carried on the session, so every link that
    reaches a player is a live one. `expires_in_seconds` is published so a
    client can decide whether to reuse the link it holds or ask for another —
    without it the only way to find out is to play and fail.
    """

    url: str
    expires_in_seconds: int


class SessionRead(BaseModel):
    """What a client is told about its own session.

    Deliberately narrower than the row. `last_progress_at`,
    `last_user_speech_at` and `grace_started_at` are metering machinery: the
    first two describe how the reaper decides a room is abandoned, and
    publishing them tells a client how to look alive without being there.

    `grace_started_at` is left out for a product reason rather than a security
    one — it is precisely "you have run out and are on borrowed time", which is
    the depleting counter Product.md §4.6 forbids showing. The room keeps
    running either way; the user has no decision to make from it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    state: SessionState
    started_at: datetime
    end_reason: EndReason | None = None
    settled_at: datetime | None = None

    #: What this room is grounded in, fixed when it started.
    #:
    #: Echoed back rather than left to the client to remember, because a client
    #: that reopens the app mid-session has no other way to find out — and
    #: "which deck is this room attacking" is not a question the user should
    #: have to answer from memory.
    material_ids: list[uuid.UUID] = Field(default_factory=list)

    #: Whether this room can still be heard. Never a URL — see `RecordingRead`.
    recording: RecordingRead = Field(
        default_factory=lambda: RecordingRead(state=RecordingState.NOT_RECORDED)
    )

    #: Who is in this room, in the order they were seated. Fixed when it started,
    #: for the same reason and echoed back for the same reason.
    #:
    #: Names rather than rendered panelists. The client resolves them against the
    #: archetype catalogue, which it needs anyway to offer the picker — and
    #: inlining persona and attack strategy here would put the room's own attack
    #: plan in a response the user can read, which is not a thing to hand
    #: somebody rehearsing against it.
    archetypes: list[str] = Field(default_factory=list)


class SessionStarted(SessionRead):
    """The only response that carries a stream ticket.

    Separate from `SessionRead` rather than a nullable field on it, because the
    two are answers to different questions. Reading a session or ending one
    must not mint a credential, and a shared schema is how that eventually
    happens by accident — a handler returns the wider type, and a ticket
    appears on a response nobody meant to put one on.
    """

    #: Spend it on the stream socket, once, within seconds. Named for what it
    #: opens rather than `token`, so it is never mistaken in a client for the
    #: credential that authenticates everything else.
    stream_ticket: str


class PhaseSpanRead(BaseModel):
    """One stretch of one phase.

    `ended_at` null means the phase is still open — for interrogation that also
    means the meter is running, which is why it is never inferred from the
    session state.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    phase: SessionPhase
    started_at: datetime
    ended_at: datetime | None = None
