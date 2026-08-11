"""Session states and read models.

The state machine is specified in `docs/minutes-ledger-and-sessions.md` Part 2.
"""

from enum import Enum


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
