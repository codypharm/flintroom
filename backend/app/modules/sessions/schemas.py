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
