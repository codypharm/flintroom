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

    #: Extra response headers. Empty for almost everything — a header is part
    #: of the protocol, not part of the message, and only a few failures have
    #: something protocol-level to say.
    headers: dict[str, str] = {}

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


class RateLimited(FlintroomError):
    """Too many attempts in too short a window.

    429 rather than 403: nothing about the caller was denied, and the correct
    client behaviour is to wait rather than to re-authenticate or give up.

    The message says nothing about which limit was hit or how much budget is
    left. `Retry-After` is the one thing worth telling them, because without it
    a client either gives up or retries immediately, and both are worse for us
    than a client that waits the right amount of time.
    """

    status_code = 429
    code = "rate_limited"
    message = "Too many attempts. Please wait a moment and try again."

    def __init__(self, retry_after_seconds: int, **context: Any) -> None:
        super().__init__(**context)
        self.headers = {"Retry-After": str(retry_after_seconds)}


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


class MaterialNotFound(NotFound):
    """No such material, or not this caller's.

    Deliberately one error for both. Telling a prober which material ids exist
    is a slow enumeration of every deck on the platform, and the honest answer
    to "may I have this" is the same either way.
    """

    code = "material_not_found"
    message = "No such material."


# --- Refused uploads ------------------------------------------------------
#
# Both are raised *before* a presigned URL is issued, so neither costs the user
# an upload. They are deliberately different errors rather than one "we won't
# take that", because only one of them has anything to sell.


class MaterialTooLarge(FlintroomError):
    """Over the caller's per-file byte cap.

    The one legitimate paywall in ingestion: a pre-session refusal on a limit
    that is published on the tier card the user chose their plan against. That
    is a different thing from interrupting a live session to show a paywall,
    which CLAUDE.md forbids outright — do not let this precedent drift toward
    it.

    The message is assembled by the caller because it names three numbers and a
    tier, none of which this class can know. Its tone is fixed: state the file's
    size, state the cap, name the cheapest tier that would accept it. No
    apology, no verb of persuasion — the upgrade is offered as an available fact
    and the client renders the button.
    """

    status_code = 413
    code = "material_too_large"
    message = "That file is larger than your plan accepts."


class UnsupportedMaterialType(FlintroomError):
    """Not a format the extraction pipeline can read.

    Never carries an upgrade, because no tier accepts an executable. Keeping it
    separate from `MaterialTooLarge` is what stops a wrong-type refusal quietly
    growing an upsell it has no right to make.
    """

    status_code = 415
    code = "unsupported_material_type"
    message = "We cannot read that kind of file."


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


class SessionNotLive(BusinessRuleViolation):
    """The room is no longer running, so stop metering it.

    Distinct from `InvalidStateTransition` because nothing is being transitioned
    — the meter is asking to charge or to move the grace clock on a session that
    closed underneath it. The caller's correct response is to stop ticking, and
    that is a different instruction from "that move is illegal".
    """

    code = "session_not_live"
    message = "That session is no longer running."


class InvalidMaterialState(BusinessRuleViolation):
    """That material cannot move the way the caller asked.

    Separate from `InvalidStateTransition`, which is about sessions: the two
    machines have nothing in common, and one shared error would make every log
    search for either return both.
    """

    code = "invalid_material_state"
    message = "That material is not in a state that allows this."


class MaterialNotUploaded(BusinessRuleViolation):
    """The client said the bytes landed, and there is no object there.

    Separate from `InvalidMaterialState`: the material is in exactly the right
    state, and the store disagrees with the client about the world. The caller's
    correct response is to upload again, not to stop asking.
    """

    code = "material_not_uploaded"
    message = "We did not receive that file. Please upload it again."


class MaterialNotReady(BusinessRuleViolation):
    """A room was asked to ground itself in a deck that is not finished.

    Not a race the client should paper over by retrying blindly — extraction of
    a long deck is minutes — but it is genuinely temporary, and the message says
    so rather than implying the file is bad.

    Why this is a refusal rather than a wait: `docs/ingestion.md` refused to let
    slides land during a live interrogation on grounding correctness. The
    Auditor's reference set would change mid-session, so the same spoken claim
    could pass at minute two and fail at minute six, and *"why did the panel
    miss that"* stops having an answer.

    One error, two messages, chosen at the raise like `MaterialTooLarge`. A deck
    still extracting and a deck that failed are the same refusal to the room and
    opposite advice to the person: wait, or upload it again. Telling somebody to
    wait for a deck that will never finish is how a user sits watching a spinner
    that is not spinning.

    A 422 rather than a 409, following `docs/ingestion.md` and CLAUDE.md's rule
    that business-rule violations are 422. The state is a fact about the
    material, not a conflict with another writer.
    """

    code = "material_not_ready"
    message = "That material is still being read. Start the room in a moment."


class ExtractionIncomplete(BusinessRuleViolation):
    """Something tried to settle a deck that was only partly read.

    A programming error rather than anything a user did, and typed rather than
    an assertion because of what it guards. A long deck takes several model
    calls and one can fail after the others have been paid for; settling that
    would mark the material `ready`, and `ready` is the promise the panel
    grounds itself on. Since the source document is deleted on success, the gap
    would be permanent and invisible.

    The correct response is `fail_extraction`, which records what the attempt
    cost and leaves the material `failed`.
    """

    code = "extraction_incomplete"
    message = "That material was not fully read."


class MaterialTooManyPages(BusinessRuleViolation):
    """More pages than the caller's tier extracts from one file.

    Cannot be refused at upload time the way the byte cap is — counting pages
    means reading the file — so this arrives after the bytes have landed, and
    the material fails terminally rather than waiting: no window rolls over into
    a file being shorter.

    Distinct from the monthly page budget, which *is* a window and does leave a
    material `pending`. Sharing an error between them would make the two
    indistinguishable in a log, and they call for opposite handling.
    """

    code = "material_too_many_pages"
    message = "That file has more pages than your plan extracts."


class MaterialUnreadable(BusinessRuleViolation):
    """The bytes are not the document they were declared to be.

    The presigned upload binds the type the client *sent* to the type we
    recorded; it cannot make the claim true. This is where the difference
    surfaces, and it is typed rather than an escaping exception because it runs
    inside the extraction sweep — where an unhandled error marks nothing and
    leaves the material claimed until the requeue notices.
    """

    code = "material_unreadable"
    message = "We could not read that file. It may be damaged or password-protected."


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
