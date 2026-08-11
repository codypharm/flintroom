"""The error hierarchy.

CLAUDE.md fixes the mapping: business rule violations are 422, auth failures
401/403, missing resources 404, duplicate actions 409, external provider
failures 502 — and a duplicate action is never a 500. Encoding that on the
exceptions keeps every route honest without each one re-deciding.

Services raise these. Routers do not translate them; a single handler does.
"""

import pytest

from app.core.errors import (
    AccountNotFound,
    ActiveSessionExists,
    FlintroomError,
    InsufficientEntitlement,
    InvalidStateTransition,
    NotAuthenticated,
    ProviderUnavailable,
)


def test_each_error_carries_the_status_code_claude_md_requires():
    assert NotAuthenticated().status_code == 401
    assert InsufficientEntitlement(user_id="u-1", action="start_session").status_code == 403
    assert AccountNotFound(user_id="u-1").status_code == 404
    assert ActiveSessionExists(user_id="u-1").status_code == 409
    assert InvalidStateTransition(current="settled", attempted="active").status_code == 422
    assert ProviderUnavailable(provider="elevenlabs").status_code == 502


def test_an_error_carries_context_for_the_log_line():
    """The context that makes a failure diagnosable travels with the error.

    Without it the handler logs "403 Forbidden" and the reason is gone, which is
    exactly the case CLAUDE.md requires to be logged with user_id and the
    attempted action.
    """
    error = InsufficientEntitlement(user_id="u-1", action="start_session")

    assert error.context == {"user_id": "u-1", "action": "start_session"}
    assert error.code == "insufficient_entitlement"


def test_every_error_is_a_flintroom_error():
    """One base class, so a handler can catch ours and let real bugs through.

    A bare `except Exception` would swallow programming errors and turn them
    into tidy 4xx responses, which is how a crash becomes invisible.
    """
    for error in (
        NotAuthenticated(),
        AccountNotFound(user_id="u-1"),
        ActiveSessionExists(user_id="u-1"),
        ProviderUnavailable(provider="elevenlabs"),
    ):
        assert isinstance(error, FlintroomError)

    assert not issubclass(FlintroomError, Exception.__class__)
    with pytest.raises(FlintroomError):
        raise AccountNotFound(user_id="u-1")


def test_the_client_facing_payload_excludes_internal_context():
    """A 403 tells the caller what failed, not what we know about them.

    Context is for our logs. Echoing it back leaks internal identifiers and
    reasoning to whoever is probing the endpoint.
    """
    error = InsufficientEntitlement(user_id="u-1", action="start_session")

    payload = error.to_response()

    assert payload == {"error": {"code": "insufficient_entitlement", "message": error.message}}
    assert "u-1" not in str(payload)
