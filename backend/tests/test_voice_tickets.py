"""Tickets — the credential that gets a socket past the door.

A WebSocket handshake cannot carry an `Authorization` header from a browser, and
CLAUDE.md forbids mobile-only assumptions that a web client would later have to
unpick. So the socket is admitted by a ticket in the query string instead, and
everything about the ticket's design follows from where it is written down:
query strings end up in access logs, proxy logs and browser history.

Hence single-use and short-lived. A ticket that leaks is a ticket that has
almost certainly already been spent, and is worthless within half a minute
regardless.
"""

from __future__ import annotations

import inspect

from datetime import timedelta

import pytest
from sqlalchemy import func, update

from app.core.errors import NotAuthenticated
from app.modules.voice.models import VoiceTicket
from app.modules.voice.tickets import VoiceTicketService


async def _expire(db) -> None:
    """Age every outstanding ticket past its window.

    Postgres' clock again, not Python's: `expires_at` is compared against
    `now()` inside the redeeming statement, so freezing the interpreter's clock
    would move nothing the query reads.
    """
    await db.execute(
        update(VoiceTicket).values(expires_at=func.now() - timedelta(seconds=1))
    )
    await db.commit()


async def test_a_freshly_minted_ticket_admits_its_holder(
    db, sessions, funded_account
):
    """The happy path: mint at start, spend at connect.

    Redeeming answers with the user the ticket was minted for rather than a
    bare yes. The socket has no other way to learn who is on the other end —
    there is no header to read — so the ticket is the identity, not just the
    permission.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    tickets = VoiceTicketService(db)

    ticket = await tickets.mint(session_id=session.id, user_id=funded_account.user_id)

    assert (
        await tickets.redeem(ticket=ticket, session_id=session.id)
        == funded_account.user_id
    )


async def test_a_ticket_cannot_be_spent_twice(db, sessions, funded_account):
    """Single use, which is what makes a ticket in a URL survivable.

    Query strings are written to access logs, proxy logs and browser history.
    A ticket recovered from any of them has, by then, almost always been spent
    already — and a spent ticket opens nothing.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    tickets = VoiceTicketService(db)
    ticket = await tickets.mint(session_id=session.id, user_id=funded_account.user_id)

    await tickets.redeem(ticket=ticket, session_id=session.id)

    with pytest.raises(NotAuthenticated):
        await tickets.redeem(ticket=ticket, session_id=session.id)


async def test_a_ticket_that_sat_too_long_is_refused(db, sessions, funded_account):
    """And the one recovered *before* it was spent is worthless in half a minute.

    The window covers the gap between the response to `POST /sessions` and the
    handshake that follows it, and nothing else. It is not a session length.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    tickets = VoiceTicketService(db)
    ticket = await tickets.mint(session_id=session.id, user_id=funded_account.user_id)

    await _expire(db)

    with pytest.raises(NotAuthenticated):
        await tickets.redeem(ticket=ticket, session_id=session.id)


async def test_a_ticket_does_not_open_a_room_it_was_not_minted_for(
    db, sessions, ledger, funded_account
):
    """A ticket is one room's key, not a credential.

    Without this binding a leaked ticket would be pointed at somebody else's
    session — and since redeeming is also how the socket learns who is on the
    other end, that would hand the holder another user's identity for the
    duration of the stream, not merely access to a room.
    """
    from tests.conftest import create_funded_account

    stranger = await create_funded_account(db, ledger)
    mine = await sessions.start(user_id=funded_account.user_id)
    theirs = await sessions.start(user_id=stranger.user_id)

    tickets = VoiceTicketService(db)
    ticket = await tickets.mint(session_id=mine.id, user_id=funded_account.user_id)

    with pytest.raises(NotAuthenticated):
        await tickets.redeem(ticket=ticket, session_id=theirs.id)


def test_the_database_dependency_resolves_on_a_socket_as_well_as_a_request():
    """`get_db` has to serve the stream socket, and took a `Request`.

    A WebSocket connection is not a `Request`, so FastAPI could not build the
    argument and every attempt to open a room died in dependency resolution
    with `get_db() missing 1 required positional argument` — a 500 on the
    handshake, before any of our code ran.

    Nothing caught it. The route's own tests call `stream_session` directly and
    pass a session in, which is what makes them fast and which also skips the
    only part that was broken. It surfaced on the first real phone.

    Asserted against the annotation rather than by opening a socket, because
    `HTTPConnection` is precisely the fix: it is the common base of `Request`
    and `WebSocket`, and a future edit narrowing it back to `Request` would
    break rooms while leaving every HTTP test green.
    """
    from starlette.requests import HTTPConnection

    from app.core.database import get_db

    (parameter,) = inspect.signature(get_db).parameters.values()
    assert parameter.annotation is HTTPConnection
