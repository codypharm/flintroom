"""Who caused a change.

Attached to every money movement and every audit event. A delta and a reason
code say what happened; without an actor nobody can answer whether a user bought
minutes, a webhook granted them, or support credited them by hand — which is the
first question in any billing dispute.

Cross-cutting rather than billing-specific: sessions, the reaper and future admin
tooling all record the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Actor(str, Enum):
    """The kind of thing that caused a change."""

    #: Automated application behaviour — the tick loop, lazy period reset.
    SYSTEM = "system"
    #: A request made on behalf of the account holder.
    USER = "user"
    #: An external provider callback, e.g. RevenueCat.
    WEBHOOK = "webhook"
    #: The background finalizer reclaiming abandoned or stuck sessions.
    REAPER = "reaper"
    #: A human operator acting through admin tooling. Always has an actor_id.
    ADMIN = "admin"


@dataclass(frozen=True)
class ActorContext:
    """Provenance carried into a service for the duration of one operation.

    Passed at construction rather than per call, so a caller cannot attribute
    half its writes to one actor and half to another.
    """

    actor: Actor
    #: Identifies the specific webhook event, admin user, or session owner.
    #: Required for ADMIN, since "an operator did it" is not an audit trail.
    actor_id: str | None = None
    #: Ties every row written during one request together, and to the logs.
    request_id: str | None = None

    def __post_init__(self) -> None:
        if self.actor is Actor.ADMIN and not self.actor_id:
            raise ValueError("an admin action must record which operator performed it")

    @classmethod
    def system(cls, *, request_id: str | None = None) -> ActorContext:
        return cls(actor=Actor.SYSTEM, request_id=request_id)

    @classmethod
    def reaper(cls) -> ActorContext:
        return cls(actor=Actor.REAPER)
