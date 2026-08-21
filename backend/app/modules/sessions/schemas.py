"""Session states and read models.

The state machine is specified in `docs/minutes-ledger-and-sessions.md` Part 2.
"""

import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

#: How many rooms a list returns.
#:
#: Not pagination, and deliberately not pretending to be. §4.4 caps Pro at three
#: hours a month, so a heavy account's first year is a few dozen rooms — a
#: bounded list is honest about that where an unbounded one works right up until
#: it does not. Real paging is owed when the library surface exists and has
#: somewhere to put it.
RECENT_LIMIT = 50

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

#: How long the name of a rehearsal may be.
#:
#: A heading, not a description. It is drawn as one line above a run of rooms on
#: the progress screen and as the headline of a row in the Library, so anything
#: that does not fit on a phone in one line is not a name — it is a note, and
#: this is not the field for one.
REHEARSAL_NAME_LIMIT = 80


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

    #: What the presenter calls the thing they are rehearsing, or null.
    #:
    #: Optional everywhere and asked for once: a room started from scratch may
    #: name what it is about, and a re-run inherits the name of the lineage it
    #: joins without having to send it back.
    #:
    #: Bounded because this is a heading rather than a description, and a field
    #: with no length is a field somebody pastes a transcript into. Refused at
    #: 422 rather than truncated — silently storing something other than what
    #: was typed is worse than saying no.
    rehearsal_name: str | None = Field(default=None, max_length=REHEARSAL_NAME_LIMIT)

    @field_validator("rehearsal_name")
    @classmethod
    def _named_or_not_at_all(cls, given: str | None) -> str | None:
        """A field somebody tabbed through is no name, not a name of spaces.

        A lineage headed by a blank line reads as a rendering fault rather than
        as a room nobody named, and `"   " != None` is the kind of difference
        that only ever shows up on somebody's screen.
        """
        if given is None:
            return None
        return given.strip() or None

    #: The room this one repeats, or null for a fresh argument.
    #:
    #: Sent by "Run it again" in the Library. The server reads that room's
    #: lineage rather than trusting a group id from the client — see
    #: `SessionService.start`.
    repeats: uuid.UUID | None = None

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

    #: How long a saved room stays playable, in days. Response only — a client
    #: does not get to choose its own retention window, and a request schema
    #: carrying the field would imply it could.
    #:
    #: Published because the first-session disclosure has to state it. A
    #: disclosure that says rooms are saved and goes quiet on for how long is
    #: the half of the sentence that matters least to us and most to the person
    #: reading it.
    retention_days: int


class RecordingPreferenceUpdate(BaseModel):
    """Turning saving on or off. The only thing a client may set."""

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

    # `populate_by_name` because `rehearsal_id` is aliased off a model
    # property, and `model_copy(update=...)` in the router addresses it by field
    # name — without this, every constructed copy would drop it.
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    user_id: uuid.UUID

    #: The lineage this room belongs to — the argument being rehearsed across
    #: several attempts. Its own id for a room that repeats nothing, so a client
    #: groups on one field with no null case.
    #:
    #: Aliased off `Session.rehearsal`, which applies the null-means-itself
    #: rule. Reading the column directly would put the null on the wire and
    #: hand every client the same branch to get wrong.
    rehearsal_id: uuid.UUID = Field(validation_alias="rehearsal")

    #: What the presenter calls this rehearsal, or null if nobody named it.
    #:
    #: The **lineage's** name, not the row's: the newest name given to any room
    #: in the group, resolved by `rehearsals.py`. A re-run therefore reports the
    #: name it inherited even though its own column is empty, and naming a
    #: rehearsal on its fourth attempt names all four.
    #:
    #: User text. It is rendered back to whoever typed it and reaches no model
    #: — see `Session.rehearsal_name`.
    rehearsal_name: str | None = None

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

    #: The rung this room ran at, or null if it never became a room.
    #:
    #: Published so the setup screen can show the pressure a *re-run* will
    #: actually open at. A room that repeats another inherits the rung its
    #: rehearsal last ran at, and a picker still showing the account's number
    #: would state one thing and start another.
    difficulty_level: int | None = None

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


class WeakAnswerRead(BaseModel):
    """One question the room did not get a good enough answer to.

    Carries the presenter's own words back, not only a verdict. §3.5's artefact
    is *"the 6 questions you will get, and where your answers are thin"*, and a
    response of categories alone would be a scorecard — the delivery-metrics
    product this one exists to refuse.
    """

    model_config = ConfigDict(from_attributes=True)

    #: Which transcript line the question is. What sparring re-asks, and what a
    #: coaching turn cites.
    ordinal: int
    question: str
    asked_by: str

    #: What they said in reply, or null when they said nothing — which is one of
    #: the findings rather than missing data.
    answer: str | None
    weakness: str
    why: str

    #: What to reach for next time, or null when the model offered none — or
    #: offered one that invented a figure and was dropped before it got here.
    #: The forward half of a finding; `why` alone diagnoses and stops.
    next_time: str | None = None


class DebriefRead(BaseModel):
    """What the coach and the prep sheet are both grounded in.

    An object rather than a bare list, because the debrief will carry more than
    this — a coaching thread, a soft-cap warning — and a client that unpacked a
    top-level array would have to change shape when it does.

    An empty list is a real answer: this room had nothing worth raising. It is
    not the same as the refusals, which arrive as typed errors precisely so a
    client can tell "you did well" from "there is nothing here".
    """

    weak_answers: list[WeakAnswerRead]

    #: How this room compared to the one before it — `"harder"`, `"easier"`, or
    #: null when there is nothing to compare against.
    #:
    #: **A direction, never a level.** `docs/difficulty-calibration.md` decision
    #: 5: the client writes the sentence and the API states the fact. Publishing
    #: a number would put a score on the debrief screen, which is the drift
    #: toward the delivery-metrics product §1 exists to refuse — and a number is
    #: also the thing somebody would try to farm.
    #:
    #: Null on a first room, and the client says nothing rather than saying "the
    #: same as last time" about a session that does not exist. Null too when the
    #: room ran at the same rung: nothing changed, so there is nothing to
    #: mention on a screen already carrying weak answers and a coach.
    pressed: Literal["harder", "easier"] | None = None

    #: What the coach says before anybody has said anything, or null.
    #:
    #: Null in exactly two cases, and both are real rather than errors: a room
    #: whose coaching conversation started without one — reachable by a client
    #: that goes straight to the microphone — and, on the client's side of this,
    #: nothing at all to say. Greeting into the middle of an exchange would read
    #: as the coach not having been listening.
    #:
    #: **`speech` is empty on every read after the first**, and that is the
    #: whole of the cost decision. `docs/voice-cost.md` puts the expressive
    #: speaker at roughly $0.0002 a character, so a spoken opening costs about
    #: what a minute of live interrogation does — and this endpoint is re-fetched
    #: on every resume. The text is stored and recalled; the voice belongs to the
    #: arrival, and hearing it again is a request with its own endpoint.
    opening: CoachTurnRead | None = None


class TranscriptLineRead(BaseModel):
    """One line of one room, as it was said.

    `speaker` is `user` or an archetype's `name` — the same identity used in
    logs, in routing and in the room's own transcript. Never a rendered title:
    the client already resolves archetype names against the catalogue it reads
    to offer the picker, and a second spelling of "The CFO" on the wire is how
    two surfaces come to disagree about what somebody is called.
    """

    model_config = ConfigDict(from_attributes=True)

    #: Where this line falls in the room, from zero. The order is content —
    #: two lines can share a clock reading, so this is what "after" means here.
    ordinal: int
    speaker: str
    text: str

    #: When the line was **written**, which is not when the audio was heard.
    #:
    #: Published because it orients a reader — a room reads differently when you
    #: can see where the long silence was — and withheld from any claim it
    #: cannot support. Lines are written as they are said, so it is close; but
    #: "close" is the difference between a reading aid and a playback offset,
    #: and #69 exists because no true offset is recorded anywhere. Nothing
    #: should seek audio with this.
    said_at: datetime


class TranscriptRead(BaseModel):
    """A room, read back.

    An object around the list rather than a bare array, for the reason
    `DebriefRead` gives: a transcript will grow a companion — time offsets when
    #69 lands, a recording's state — and a client that unpacked a top-level
    array would have to change shape when it does.

    An empty list is a real answer rather than a refusal. A room can end before
    the panel gets a question out, and a 404 there would say the room does not
    exist, which is a different and wrong statement.
    """

    lines: list[TranscriptLineRead]


class RoomHeldRead(BaseModel):
    """One assessed room: what it put to them, what held, and how hard it was.

    **All three on one object, never in three lists.** `held` and `challenged`
    mean nothing without `level`: difficulty escalates, so a room where more got
    past somebody may simply be a room that pressed harder. A client that could
    receive the figures separately from the rung could render them separately,
    and the first thing it would draw is a trend that tells an improving
    presenter they are getting worse.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    session_id: uuid.UUID

    #: The rehearsal this room belongs to — its own id unless it repeats another.
    #:
    #: Never null. The column behind it is nullable, because a NOT NULL one
    #: would have broken inserts from the previously deployed build, and
    #: `ProgressService` collapses that with `COALESCE(rehearsal_id, id)` before
    #: it reaches here. Publishing the null would put a branch in every client
    #: forever to carry a migration detail.
    #:
    #: Aliased off `RoomHeld.rehearsal` for the same reason `SessionRead` is:
    #: the service already answers the question, and a second implementation of
    #: "which group is this in" is how two screens come to disagree.
    rehearsal_id: uuid.UUID = Field(validation_alias="rehearsal")

    #: What the presenter calls that rehearsal, or null if nobody named it.
    #:
    #: Null rather than a heading derived from the panel or the deck. A label
    #: the presenter never chose is one they cannot correct, and a run headed by
    #: a date at least says only what is true.
    rehearsal_name: str | None = None

    started_at: datetime

    #: Challenges the presenter actually had a turn at.
    #:
    #: A question a colleague talked over is in neither term. It is not a
    #: failure — #56 — and it is not a success either, because nobody answered
    #: it; counting it as held would be the same false comfort that counting it
    #: as fumbled is a false accusation.
    challenged: int
    held: int

    #: The rung this room ran at. Null for a room predating the ladder, and left
    #: null rather than guessed — `sessions.difficulty_level`'s own migration
    #: gives the reason.
    level: int | None = None


class TallyRead(BaseModel):
    """A thing, and how many *rooms* it happened in.

    Rooms rather than occurrences, because a habit is a thing that recurs. Two
    evasive answers in one bad afternoon is one room where it happened, and
    counting occurrences would let a single disastrous session read as a
    pattern — the opposite of what somebody should take from it.
    """

    name: str
    rooms: int


class ProgressRead(BaseModel):
    """A history, with no total in it.

    No average, no lifetime figure, no streak. An average across rungs is
    arithmetic over incomparable rooms, and a single number is the shape that
    invites optimising the number instead of the argument.

    Every list empty is a real answer — a new account — rather than a refusal,
    so the screen can say "you have not run a room yet".
    """

    #: Newest first: the room somebody just left is the one they are looking for.
    rooms: list[RoomHeldRead] = Field(default_factory=list)

    #: How they fail, commonest first. Only what they were at fault for — a list
    #: naming `dismissed` would be things the room did, filed under things they
    #: do.
    habits: list[TallyRead] = Field(default_factory=list)

    #: Who keeps catching them, commonest first.
    askers: list[TallyRead] = Field(default_factory=list)


class CoachTurnRead(BaseModel):
    """What the coach said, in both channels at once.

    Text as well as audio, and the text is not a convenience. `CLAUDE.md` sets
    the accessibility floor at WCAG 2.2 AA **plus live captions**, as a v1
    requirement rather than a later addition — an audio-only reply is unusable
    for part of the audience, and a client cannot caption bytes.

    `speech` is base64 because this is JSON. The alternative was two round trips
    or a stored object, and a coaching turn is heard once and dropped:
    `docs/session-retention.md` gives the interrogation's audio a per-tier
    window and says nothing about this, because nothing was going to keep it.
    """

    model_config = ConfigDict(from_attributes=True)

    text: str

    #: Base64-encoded audio of `text`, in whatever the synthesiser produces.
    speech: str

    #: What the transcriber made of the clip — the user's own words, returned
    #: to the user who said them.
    #:
    #: Published because a dictated turn is the one place a vendor's mistake is
    #: invisible without it. A transcriber that hears "twelve" for "twelve
    #: hundred" produces a coach reply that reads as though nobody was
    #: listening, and there is no way to tell that from a disagreement.
    #:
    #: It is also the middle of the sparring record. `SparringAttempt.said`
    #: already stores it, so a client could otherwise show the answer the room
    #: got and the coach's response to a newer one, with the new answer itself
    #: missing.
    #:
    #: Not the list-endpoint disclosure `CLAUDE.md` forbids: one turn, to its
    #: owner, in the response to their own speech.
    heard: str
