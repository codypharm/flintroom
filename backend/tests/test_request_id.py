"""Tying one request's rows to one another, and to the logs.

`ledger_entries` and `audit_events` have carried a `request_id` column since
they were built, and until now nothing has ever filled it. It is the field that
answers "what else happened in the same breath as this" — a settlement writes a
refund, a forgiveness and an audit row, and without a shared id they are three
rows that merely happen to share a timestamp.
"""

from __future__ import annotations

import logging
import uuid

import pytest

from app.modules.audit_log.schemas import AuditEventType
from app.modules.audit_log.service import AuditService
from app.modules.auth.tokens import AccessTokens

from tests.conftest import SECRET


@pytest.fixture
def bearer():
    def headers(user_id: uuid.UUID) -> dict[str, str]:
        token = AccessTokens(secret=SECRET).issue(user_id=user_id)
        return {"Authorization": f"Bearer {token}"}

    return headers


async def test_a_request_stamps_its_id_on_what_it_writes(
    client, funded_account, bearer, db
):
    """The tracer, and it asserts the join rather than the header.

    A response header nobody can correlate to a row is decoration. What makes
    the id worth carrying is that support can take it from a client's bug
    report and find the exact writes that request made.
    """
    response = await client.post("/v1/sessions", headers=bearer(funded_account.user_id))

    request_id = response.headers["X-Request-ID"]
    [started] = await AuditService(db).events_for_user(user_id=funded_account.user_id)

    assert started.event_type is AuditEventType.SESSION_STARTED
    assert started.request_id == request_id


async def test_two_requests_do_not_share_an_id(client, funded_account, bearer):
    """Otherwise the id groups nothing.

    The failure worth catching is an id generated once at startup, or one
    leaking between requests through a context that is never reset — both look
    identical to a correct implementation until two requests are compared.
    """
    headers = bearer(funded_account.user_id)

    first = await client.post("/v1/sessions", headers=headers)
    second = await client.post("/v1/sessions", headers=headers)

    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


async def test_log_lines_carry_the_id_without_being_told(
    client, funded_account, bearer, caplog
):
    """The other half of the join: rows to logs.

    Added by the logger rather than passed at each call site. A rule every
    caller has to remember is one some caller will forget, and the lines that
    get forgotten are the ones written on unusual paths — which are the only
    ones anybody is reading a request id to find.
    """
    headers = bearer(funded_account.user_id)
    await client.post("/v1/sessions", headers=headers)

    with caplog.at_level(logging.WARNING):
        refused = await client.post("/v1/sessions", headers=headers)

    assert refused.status_code == 409
    [denied] = [r for r in caplog.records if r.getMessage() == "active_session_exists"]
    assert denied.context["request_id"] == refused.headers["X-Request-ID"]


async def test_a_client_cannot_choose_its_own_request_id(
    client, funded_account, bearer
):
    """The id is ours, not the caller's.

    An echoed header lets any caller stamp every row it writes with the same
    id as somebody else's request — which is not a breach on its own, but it
    poisons the one field an incident is reconstructed from, and it does so
    invisibly.
    """
    response = await client.post(
        "/v1/sessions",
        headers={**bearer(funded_account.user_id), "X-Request-ID": "chosen-by-caller"},
    )

    assert response.headers["X-Request-ID"] != "chosen-by-caller"
