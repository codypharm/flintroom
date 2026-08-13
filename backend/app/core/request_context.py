"""The id of the request being served, readable from anywhere below it.

A context variable rather than a parameter threaded through every call. The id
is needed at the two ends of a deep stack — the log formatter and the two audit
tables — and nowhere in between, so passing it explicitly would put an argument
on every function that merely stands between them.

Generated here and never read from the request. An echoed `X-Request-ID` lets
any caller stamp its rows with the same id as somebody else's, which poisons the
one field an incident is reconstructed from and does it invisibly. If a load
balancer's id is wanted later, it belongs alongside ours, not instead of it.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Header the id is returned under. A client that reports a bug can quote it,
#: and support can find every row that request wrote.
REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str | None:
    """The request being served, or None outside one.

    None rather than a placeholder: the sweep loop and the reaper write rows
    too, and an invented id would suggest those writes belonged to a request
    that never existed.
    """
    return _request_id.get()


class RequestIdMiddleware:
    """Stamp each request with an id, and return it.

    Plain ASGI rather than `BaseHTTPMiddleware`, which runs the downstream app
    in a task of its own — the context is copied at that point, so a value set
    in the wrong order silently reaches nothing. At this layer the variable is
    set before the app is called and reset after, in one context.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        token = _request_id.set(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self._app(scope, receive, send_with_id)
        finally:
            # Reset rather than left set. Workers serve requests on reused
            # tasks, and a leaked id would attribute the next request's writes
            # to the previous one — a wrong answer that looks like a right one.
            _request_id.reset(token)
