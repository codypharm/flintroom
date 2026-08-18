"""What the plan a user filled in looks like on the wire.

`docs/onboarding.md` holds the answers on-device through the survey and posts
them once, at sign-up — *"a partially-created account with no configuration is a
state worth not having"*. So this is not a request body of its own today; it
rides on sign-in, and it is a schema rather than a dict because CLAUDE.md
requires one on every input and because a typo in a chip name should fail at the
edge rather than in a room.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class Answers(BaseModel):
    """The five questions, as answered.

    Every field is optional, and that is deliberate rather than lax. The survey
    can be abandoned at any point and still produce an account — the room simply
    falls back further down `composition.compose`'s chain. A required field here
    would turn "I skipped a question" into "sign-in failed", at the exact moment
    somebody has spent five screens and has nothing yet to show for it.
    """

    model_config = ConfigDict(extra="forbid")

    #: Q1 — what kind of room this is. `other` is the v2 demand signal.
    situation: str | None = Field(default=None, max_length=64)

    #: Q2 — when it happens. Null is a true answer; see `Situation.happens_on`.
    happens_on: date | None = None

    #: Q3 — what they are when they stand up.
    role: str | None = Field(default=None, max_length=32)

    #: Q4 — the chips placed on the plan, in the order the chairs were filled.
    #:
    #: Capped at eight, which is the whole archetype library. Not a validation
    #: of *which* chips — an unknown one is dropped by `composition.compose`
    #: rather than refused, and re-deciding that here would put the two rules in
    #: two places. This bound exists only so a hostile caller cannot post a
    #: megabyte of strings into an account row.
    audience: list[str] = Field(default_factory=list, max_length=8)
