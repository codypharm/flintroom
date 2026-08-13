"""Session endpoints.

Thin, per `CLAUDE.md`: parse the request, call a service, return a response.
"""

from fastapi import APIRouter, Depends, status

from app.modules.auth.dependencies import CurrentUser, rate_limit_user
from app.modules.auth.rate_limit import SESSION_START_LIMIT
from app.modules.sessions.dependencies import (
    OwnedSession,
    SessionServiceDep,
    SettlementServiceDep,
)
from app.modules.sessions.schemas import EndReason, SessionRead

router = APIRouter(tags=["sessions"])


@router.post(
    "/sessions",
    response_model=SessionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_user("session_start", SESSION_START_LIMIT))],
)
async def start_session(user_id: CurrentUser, sessions: SessionServiceDep) -> SessionRead:
    """Open a room for the caller.

    The user is taken from the credential, never from the body: a client that
    could name the account would be able to spend somebody else's minutes.
    """
    return SessionRead.model_validate(await sessions.start(user_id=user_id))


@router.get("/sessions/{session_id}", response_model=SessionRead)
async def read_session(session: OwnedSession) -> SessionRead:
    """One session, if it belongs to the caller."""
    return SessionRead.model_validate(session)


@router.post("/sessions/{session_id}/end", response_model=SessionRead)
async def end_session(
    session: OwnedSession, settlement: SettlementServiceDep
) -> SessionRead:
    """The End button: an intent, honoured by the server.

    The end reason is not taken from the body. `user_ended` is the only ending
    a client is in a position to report, and every other reason in the enum
    decides whether minutes are refunded — a client that could name one would
    be choosing its own refund.
    """
    return SessionRead.model_validate(
        await settlement.close(session_id=session.id, end_reason=EndReason.USER_ENDED)
    )
