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


class RecordingNotAvailable(NotFound):
    """There is no audio to play for this room.

    A 404, because there is nothing at that address — but its own `code`, so a
    client can tell "this room has no recording" apart from "no such session".
    Collapsing them would make a free-tier room on day thirty-one, behaving
    exactly as documented, indistinguishable from a bad session id.
    """

    code = "recording_not_available"
    message = "This session has no recording available."


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


class GrantInputInvalid(BusinessRuleViolation):
    """An operator grant refused before a single row was written.

    Only ever raised to a terminal (`scripts/grant_minutes.py`); no endpoint
    reaches it. The message says which input, since the operator fixes it.
    """

    code = "grant_input_invalid"


class InvalidStateTransition(BusinessRuleViolation):
    code = "invalid_state_transition"
    message = "That session cannot move to that state."


class SessionNotSettled(Conflict):
    """§4.1 puts settlement first: the panel finishes, then the debrief opens.

    Reading a live room would rank a conversation still happening, against a
    transcript still being written — so the same session would produce a
    different list a minute later, having already stored the first one.
    """

    code = "session_not_settled"
    message = "This session is still running."


class ClipTooLong(FlintroomError):
    """The coaching clip is larger than one spoken turn could be.

    413 rather than 422: this is about the size of the request, not about
    anything in it, and CLAUDE.md's edge-case table maps it that way.

    It exists because the coaching clip is the one upload this API *proxies*.
    Decks go straight to object storage by presigned URL and never touch the
    process; a coaching turn cannot, because it is heard once and dropped and
    presigning it would mean storing somebody's voice and owing a deletion for
    every sentence. Proxying without a ceiling is a memory-exhaustion endpoint.
    """

    code = "clip_too_long"
    status_code = 413
    message = "That recording is too long — say it in a shorter go."


class RoomHasNoQuestions(BusinessRuleViolation):
    """The panel never asked anything, so there is nothing to be grounded in.

    Deliberately not an empty list. The two mean different things to a client:
    an empty list is *"you did well"*, and this is *"there is no session here"*.
    A coach with nothing to cite would have to invent, which CLAUDE.md refuses.
    """

    code = "room_has_no_questions"
    message = "This session ended before the panel asked anything."


class RoomBroke(BusinessRuleViolation):
    """The provider failed, so the minutes are already back in the balance.

    `docs/debrief-and-sparring.md` decision 7: a restart is both cheaper for the
    user and more honest than coaching them through a session the product broke.

    The code carries the product decision, not just the refusal — an app that
    only saw a 422 could not tell "your minutes are back, start again" from
    "something went wrong."
    """

    code = "room_broke"
    message = (
        "This session was cut short by a technical fault. Your minutes have "
        "been returned \u2014 start a fresh room."
    )


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


class MaterialInUse(BusinessRuleViolation):
    """A deck a room is still standing on cannot be pulled out from under it.

    The one refusal in ingestion that protects a *session* rather than a file.
    The Auditor cross-checks live speech against this material's claims, so
    deleting them mid-interrogation leaves the user paying metered minutes for a
    panel that has quietly lost the ability to catch anything — a failure with no
    symptom, which is the kind this codebase refuses to ship.

    Bounded, and the message says how: a session is capped at twelve minutes and
    the user is holding the device that ends it. That is what makes a refusal
    honest here rather than an obstacle — deletion is delayed by an action the
    person asking is already able to take.
    """

    code = "material_in_use"
    message = "That material is in a room you are still in. End the session first."


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


class PanelTooLarge(BusinessRuleViolation):
    """More archetypes than this plan seats.

    Names the plan that would take it, as `MaterialTooLarge` does. A limit
    somebody hits is the one honest moment to say what lifts it, and a bare
    refusal is a dead end at the exact point the user is deciding what this is
    worth to them.

    422 rather than 403: this is not a permission the account lacks, it is a
    request the plan does not fit. The user changes the request or the plan, and
    either way there is something to do.
    """

    code = "panel_too_large"
    message = "That is more panelists than your plan seats."


class TitleAlreadyUsed(BusinessRuleViolation):
    """Two live panelists on one account with the same name on them.

    Refused rather than allowed, because the picker shows titles and two of one
    word is a list that cannot be read — and the Library, the transcript and the
    debrief all name panelists the same way.

    Scoped to the account and to the living. Another user's identical title is
    none of this account's business, and a retired one frees the word: the
    retired row keeps its own for the rooms that used it, which is what the
    partial index on `archived_at IS NULL` expresses.
    """

    code = "title_already_used"
    message = "You already have a panelist with that name."


class ArchetypeNotFound(NotFound):
    """A panelist nobody in the library answers to.

    Refused rather than skipped. Dropping it would seat a smaller room than the
    user assembled, and they would discover it by noticing somebody never spoke —
    which reads as a broken panel rather than a rejected request.
    """

    code = "archetype_not_found"
    message = "No such panelist."


class PanelWithoutAShippedVoice(BusinessRuleViolation):
    """Every seat filled by a panelist the user wrote themselves.

    Refused at composition rather than at start, because two things break and
    one of them breaks quietly.

    **The room opens in silence.** `openers` are hand-written per archetype and
    a row a user typed carries none, so `opening.NoOneToOpen` is raised — an
    exception whose own docstring says it is *"reachable only by a room seated
    entirely from custom archetypes"*.

    **And nobody warns them at sixty seconds.** `nudges` is the same shape, and
    is what the room says before the ninety-second idle timeout reaps and
    refunds (#24). A room with nobody to say it reaps in silence, for somebody
    who by then *"has stopped looking at the phone"*. That one costs them a
    room and never explains why.

    Here rather than at `POST /v1/sessions` deliberately. A refusal at Start is
    a constraint discovered on a screen somebody has already committed to, and
    the metering rules are explicit that a room in progress is never where that
    happens. Better it is simply not an arrangement the picker will build.

    422, like `DuplicatePanelist`: nothing is in conflict and no permission is
    missing — the request is not a room.
    """

    code = "panel_without_a_shipped_voice"
    message = "A room needs at least one of our panelists in it."


class DuplicatePanelist(BusinessRuleViolation):
    """The same archetype seated twice in one room.

    Refused rather than deduped, on the same reasoning as `ArchetypeNotFound`:
    collapsing it silently seats a smaller room than the user assembled, and they
    learn about it by noticing the panel is thinner than they chose.

    422 rather than 409. Nothing is in conflict with anything — the request is
    simply not a room, in the same way a request for four panelists on a
    three-seat plan is not one.
    """

    code = "duplicate_panelist"
    message = "That panelist is already in the room."


class NoMinutesRemaining(BusinessRuleViolation):
    """Raised when *starting*, never mid-session.

    A live interrogation is never interrupted for balance — Product.md §4.5. The
    panel finishes, settlement runs, and the user is handed to debrief.
    """

    code = "no_minutes_remaining"
    message = "You are out of interrogation minutes."


class DailyCeilingReached(BusinessRuleViolation):
    """The runaway-cost circuit breaker, tripped.

    Not about the user's balance and not a paywall. It bounds what the
    *providers* can be made to charge us in a day for one account — the abuse
    shape `docs/voice-cost.md` describes, where a room ended under the meter's
    first tick is free to the user and still cost three vendors something.

    Raised only at a start, like `NoMinutesRemaining` and for the same reason:
    Product.md §4.5 forbids interrupting a live interrogation, so a room that
    opens is a room that finishes however much it costs.

    **The message says nothing about spend.** The figure is ours and telling
    somebody what their rehearsing costs us invites a conversation the product
    does not want to have — and this will occasionally fire on a heavy paying
    user, whose reaction to "you have cost us fifteen dollars" would be a
    reasonable one we would deserve.
    """

    code = "daily_ceiling_reached"
    message = "This account has opened its limit of rooms for now."


# --- External providers ---------------------------------------------------


class WebhookRejected(FlintroomError):
    """A callback that did not prove it came from who it says.

    400 rather than 401, and the difference matters to the sender: a webhook has
    no credential to re-present and no user to re-authenticate. The request is
    malformed as far as this endpoint is concerned, and RevenueCat retries a
    non-200 five times over roughly two and a half hours — which for a forged
    request is four extra chances that must also fail.

    The reason lives in `context`, never in the response. It goes to the audit
    row and the log, because *"bad signature"* against *"stale timestamp"* is the
    difference between somebody guessing a secret and a clock drifting — and
    telling the sender which one it was is telling an attacker how close they are.
    """

    status_code = 400
    code = "webhook_rejected"
    message = "That callback could not be verified."


class WebhookUnconfigured(FlintroomError):
    """This deployment cannot verify callbacks, so it refuses them all.

    503 rather than 500: nothing is broken, a secret is missing, and the
    condition clears when it is set. RevenueCat's retries then deliver the events
    that arrived in the gap, which is exactly the behaviour wanted from a
    deployment that came up half-configured.

    Deny by default, and the alternative decides it: an unverifiable endpoint
    that accepted everything would grant minutes to anyone who found it, while
    looking perfectly healthy — 200 to every caller and nothing in any log.
    """

    status_code = 503
    code = "webhook_unconfigured"
    message = "Callbacks are not available."


class DeletionSweepUnconfigured(FlintroomError):
    """The account-deletion sweep was started without an object store.

    Never reaches a client — the only caller is the sweep loop, and it is
    logged there. Typed anyway, so that the thing which stops a purge is a
    named condition rather than an `AttributeError` two frames into a bucket
    call.

    Deny by default, and here the default is unusually expensive to get wrong:
    a purge that ran without the store would destroy `session_recordings` and
    `materials`, the only rows that know an object exists, leaving audio and
    decks in the bucket with nothing left pointing at them.
    """

    status_code = 503
    code = "deletion_sweep_unconfigured"
    message = "Account deletion is not available."


class ProviderUnavailable(FlintroomError):
    """An upstream service failed. Never let its exception type escape.

    CLAUDE.md: catch the specific SDK exception, log with full context, and
    surface 502. Affected minutes are refunded by the session finalizer.
    """

    status_code = 502
    code = "provider_unavailable"
    message = "A service we depend on is unavailable. Please try again."
