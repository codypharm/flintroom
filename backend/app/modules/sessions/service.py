"""The session state machine.

Server-authoritative by design: the End button sends an *intent*, the server
decides. Nothing money-relevant is taken from the client.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.errors import ActiveSessionExists
from app.core.logging import get_logger
from app.modules.sessions.models import Session
from app.modules.sessions.schemas import SessionState

#: The states that hold a user's one-session lock. Released at `settled` and
#: `failed` — neither costs anything to keep around.
LOCK_HOLDING_STATES = (
    SessionState.PROVISIONING,
    SessionState.ACTIVE,
    SessionState.FINALIZING,
)

log = get_logger(__name__, tag="sessions")


class SessionService:
    """The only path through which session state changes."""

    def __init__(self, db: AsyncSession, actor: ActorContext | None = None) -> None:
        self._db = db
        self._actor = actor or ActorContext.system()

    async def start(self, *, user_id: uuid.UUID) -> Session:
        """Open a session in `provisioning`.

        Bills nothing: the room has not opened yet. The first ledger entry comes
        from the first tick after the voice channel is established.
        """
        if (existing := await self._active_session(user_id)) is not None:
            raise ActiveSessionExists(user_id=str(user_id), session_id=str(existing.id))

        session = Session(user_id=user_id, state=SessionState.PROVISIONING)
        self._db.add(session)
        try:
            await self._db.commit()
        except IntegrityError as exc:
            # A racer committed between our check and our insert. The database
            # is the arbiter, and losing the race is an ordinary product outcome
            # — the user has a session, just not this one. Never a 500.
            await self._db.rollback()
            if not self._is_one_live_session_violation(exc):
                raise
            raise ActiveSessionExists(user_id=str(user_id)) from exc

        log.info("session_started", user_id=str(user_id), session_id=str(session.id))
        return session

    @staticmethod
    def _is_one_live_session_violation(exc: IntegrityError) -> bool:
        """Only the one-live-session index means "you already have a session".

        Checked by name so that some other constraint failing is not silently
        reported to the user as a duplicate session — that would turn a real bug
        into a plausible-looking 409 and hide it.
        """
        return "uq_sessions_one_live_per_user" in str(getattr(exc, "orig", exc))

    async def _active_session(self, user_id: uuid.UUID) -> Session | None:
        """The session currently holding this user's lock, if any.

        `settled` and `failed` are deliberately excluded: a user sitting in
        yesterday's debrief is not blocked from starting a fresh interrogation,
        because debrief is unmetered and holds no resources.
        """
        result = await self._db.execute(
            select(Session)
            .where(Session.user_id == user_id, Session.state.in_(LOCK_HOLDING_STATES))
            .limit(1)
        )
        return result.scalar_one_or_none()
