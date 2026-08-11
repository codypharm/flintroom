"""The session lifecycle — the state machine the ledger hangs off.

Metering boundary (CLAUDE.md, Product.md §4.1): only interrogation is metered.
These tests exist mostly to prove that money and state stay in agreement.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.errors import ActiveSessionExists
from app.modules.sessions.models import Session as SessionModel
from app.modules.sessions.schemas import SessionState
from app.modules.sessions.service import SessionService


async def test_starting_a_session_provisions_it_before_anything_is_billed(
    sessions, ledger, account
):
    """`provisioning` holds the lock but bills nothing.

    That is the whole reason it is a distinct state rather than starting
    `active` optimistically: ElevenLabs agent spin-up takes real time and can
    fail before any audio exists, and a user must never be charged for a room
    that never opened.
    """
    session = await sessions.start(user_id=account.user_id)

    assert session.state is SessionState.PROVISIONING
    assert session.settled_at is None
    assert await ledger.entries(user_id=account.user_id) == []


async def test_the_database_refuses_a_state_outside_the_five(db, account):
    """A schema guard, deliberately reaching past the service.

    Every other test here goes through `SessionService` because that is the
    only path the application uses. This one does not: the constraint exists
    precisely to catch a bug that *bypasses* the service, so exercising it
    through the service would prove nothing. If this is ever the only way a bad
    state is caught, something upstream has already gone wrong — that is the
    point of defense in depth.
    """
    with pytest.raises(IntegrityError):
        await db.execute(
            text(
                "INSERT INTO sessions (id, user_id, state) VALUES (:id, :user_id, 'paused')"
            ),
            {"id": uuid.uuid4(), "user_id": account.user_id},
        )
        await db.commit()


async def test_starting_a_second_session_while_one_is_in_flight_is_refused(sessions, account):
    """One live interrogation per user.

    This is the cost circuit breaker the design note leans on instead of a hard
    daily cap: a user cannot run two metered rooms at once, so runaway spend is
    bounded by wall-clock time rather than by refusing them on their highest
    stakes day.
    """
    await sessions.start(user_id=account.user_id)

    with pytest.raises(ActiveSessionExists):
        await sessions.start(user_id=account.user_id)


async def test_devices_racing_to_start_produce_one_session_and_the_rest_refused(
    engine, db, account
):
    """The design note's edge case 7: one session and one 409, never two.

    The service-level check cannot see an uncommitted sibling transaction, so
    every racer passes it. Only the database can arbitrate, which is why the
    one-active-session rule is a constraint and not merely a query.

    Two details make this test able to fail, and both were found by watching it
    pass when the bug was present:

    - **Connections are established before the race.** With a cold pool the
      first racer holds the only live connection through its whole insert, and
      the others do not get their SELECT served until after it commits — so
      they see the committed row and the test passes for a reason that has
      nothing to do with correctness. Production runs a warm pool.
    - **Five racers, not two.** Two reproduce the bug only on a favourable
      interleaving.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    racers = [factory() for _ in range(5)]
    await asyncio.gather(*(session.execute(text("SELECT 1")) for session in racers))

    gate = asyncio.Event()

    async def start_once(session):
        await gate.wait()
        try:
            return await SessionService(session).start(user_id=account.user_id)
        except ActiveSessionExists:
            return None

    tasks = [asyncio.create_task(start_once(session)) for session in racers]
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(*tasks)

    for session in racers:
        await session.close()

    assert sum(result is not None for result in results) == 1

    live = (
        await db.execute(
            select(func.count())
            .select_from(SessionModel)
            .where(SessionModel.user_id == account.user_id)
        )
    ).scalar_one()
    assert live == 1
