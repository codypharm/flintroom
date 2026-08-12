"""Session states and read models.

The state machine is specified in `docs/minutes-ledger-and-sessions.md` Part 2.
"""

import uuid
from datetime import datetime, timedelta
from enum import Enum

from pydantic import BaseModel, ConfigDict

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
