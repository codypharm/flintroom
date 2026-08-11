"""Typed application errors.

Services raise these; routers do not translate them. A single exception handler
turns them into responses, so the status code for a given failure is decided
once here rather than re-argued in every endpoint.

The split that matters: `message` and `code` go to the client, `context` goes to
the log. Merging them leaks internal identifiers to whoever is probing an
endpoint; dropping the context leaves a 403 with no way to find out why.

Never raise bare `Exception`, and never catch broadly enough to swallow one —
an unexpected exception must stay a 500 and a traceback, because that is a bug
and hiding it behind a tidy 4xx is how a crash becomes invisible.
"""

from __future__ import annotations

from typing import Any


class FlintroomError(Exception):
    """Base for every deliberate failure the application raises."""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "Something went wrong."

    def __init__(self, message: str | None = None, **context: Any) -> None:
        self.message = message or type(self).message
        self.context: dict[str, Any] = context
        super().__init__(self.message)

    def to_response(self) -> dict[str, Any]:
        """The client-facing payload. Deliberately excludes `context`."""
        return {"error": {"code": self.code, "message": self.message}}


# --- Authentication and authorisation ------------------------------------


class NotAuthenticated(FlintroomError):
    status_code = 401
    code = "not_authenticated"
    message = "Authentication required."


class InsufficientEntitlement(FlintroomError):
    """Authenticated, but not entitled to this action.

    CLAUDE.md requires these logged with the user and the attempted action, so
    both are expected in context.
    """

    status_code = 403
    code = "insufficient_entitlement"
    message = "Your plan does not include this."


# --- Missing resources ----------------------------------------------------


class NotFound(FlintroomError):
    status_code = 404
    code = "not_found"
    message = "Not found."


class AccountNotFound(NotFound):
    code = "account_not_found"
    message = "No ledger account for this user."


class SessionNotFound(NotFound):
    code = "session_not_found"
    message = "No such session."


# --- Conflicts ------------------------------------------------------------


class Conflict(FlintroomError):
    status_code = 409
    code = "conflict"
    message = "That conflicts with the current state."


class ActiveSessionExists(Conflict):
    """One interrogation at a time, per Product.md.

    This is also the runaway-cost circuit breaker, so it is a real product rule
    rather than a database convenience.
    """

    code = "active_session_exists"
    message = "You already have a session running."


class LedgerConflict(Conflict):
    """Concurrent write conflict on the ledger — roll back and retry."""

    code = "ledger_conflict"
    message = "Your balance was being updated. Try again."


# --- Business rules -------------------------------------------------------


class BusinessRuleViolation(FlintroomError):
    status_code = 422
    code = "business_rule_violation"
    message = "That is not allowed right now."


class InvalidStateTransition(BusinessRuleViolation):
    code = "invalid_state_transition"
    message = "That session cannot move to that state."


class NoMinutesRemaining(BusinessRuleViolation):
    """Raised when *starting*, never mid-session.

    A live interrogation is never interrupted for balance — Product.md §4.5. The
    panel finishes, settlement runs, and the user is handed to debrief.
    """

    code = "no_minutes_remaining"
    message = "You are out of interrogation minutes."


# --- External providers ---------------------------------------------------


class ProviderUnavailable(FlintroomError):
    """An upstream service failed. Never let its exception type escape.

    CLAUDE.md: catch the specific SDK exception, log with full context, and
    surface 502. Affected minutes are refunded by the session finalizer.
    """

    status_code = 502
    code = "provider_unavailable"
    message = "A service we depend on is unavailable. Please try again."
