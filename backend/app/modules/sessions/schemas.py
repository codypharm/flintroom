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
