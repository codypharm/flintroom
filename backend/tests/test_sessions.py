"""The session lifecycle — the state machine the ledger hangs off.

Metering boundary (CLAUDE.md, Product.md §4.1): only interrogation is metered.
These tests exist mostly to prove that money and state stay in agreement.
"""

import asyncio
import uuid

import pytest
from freezegun import freeze_time
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.errors import ActiveSessionExists, InvalidStateTransition
from app.modules.audit_log.schemas import AuditEventType
from app.modules.audit_log.service import AuditService
from app.modules.sessions.models import Session as SessionModel
from app.modules.sessions.models import SessionPhaseSpan
from app.modules.sessions.schemas import EndReason, SessionPhase, SessionState
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


async def test_a_provisioned_session_becomes_active_when_the_voice_channel_opens(
    sessions, account
):
    """`active` is the only state in which the meter runs.

    The transition is server-side and follows the voice channel actually being
    established — not the client saying it is ready, because everything past
    this point costs money.
    """
    session = await sessions.start(user_id=account.user_id)

    activated = await sessions.activate(session_id=session.id)

    assert activated.state is SessionState.ACTIVE


async def test_a_settled_session_cannot_be_reactivated(sessions, account):
    """Billing is closed. Reopening it would restart the meter on a session
    that has already been paid for and forgiven.

    This is the transition that makes a table worth having rather than a set of
    independent methods: `activate` is correct from `provisioning` and a
    money-losing bug from `settled`, and nothing about the method itself says
    which.
    """
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await sessions.begin_finalizing(session_id=session.id, end_reason=EndReason.USER_ENDED)
    await sessions.settle(session_id=session.id)

    with pytest.raises(InvalidStateTransition):
        await sessions.activate(session_id=session.id)


async def test_settling_releases_the_lock_so_a_new_session_can_start(sessions, account):
    """`settled` means billing closed, not session closed.

    The user still has an unmetered debrief and sparring waiting on the session
    just finished (Product.md §3.5). Holding the lock through that would block
    them from rehearsing again — refusing the paid feature in order to protect
    a resource that is no longer held.
    """
    first = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=first.id)
    await sessions.begin_finalizing(session_id=first.id, end_reason=EndReason.USER_ENDED)
    await sessions.settle(session_id=first.id)

    second = await sessions.start(user_id=account.user_id)

    assert second.id != first.id
    assert second.state is SessionState.PROVISIONING


async def test_a_spin_up_that_never_completes_fails_without_billing_or_holding_the_lock(
    sessions, ledger, account
):
    """`provisioning → failed`, the branch that exists because agents die.

    Nothing was billed, so there is nothing to settle and nothing to refund —
    which is exactly why this is a separate terminal state rather than a walk
    through `finalizing`. Settling a session that never opened would write a
    zero-value close and make cost reports count a room that never existed.
    """
    session = await sessions.start(user_id=account.user_id)

    failed = await sessions.fail(session_id=session.id)

    assert failed.state is SessionState.FAILED
    assert failed.end_reason is EndReason.PROVISIONING_FAILED
    assert failed.settled_at is None
    assert await ledger.entries(user_id=account.user_id) == []

    # The lock is released: a failed spin-up must not lock the user out.
    assert (await sessions.start(user_id=account.user_id)).id != session.id


async def test_settlement_can_be_retried_after_dying_partway_through(sessions, account):
    """`finalizing → finalizing` is legal on purpose.

    Settlement writes a final tick, any refunds, and grace forgiveness. A crash
    between those leaves a session that is neither running nor closed, and the
    reaper's only safe move is to run settlement again. If re-entering
    `finalizing` were an error the reaper could not retry, and the session would
    hold the user's lock forever — the one failure no user action can resolve.
    """
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await sessions.begin_finalizing(session_id=session.id, end_reason=EndReason.IDLE_TIMEOUT)

    resumed = await sessions.begin_finalizing(
        session_id=session.id, end_reason=EndReason.IDLE_TIMEOUT
    )

    assert resumed.state is SessionState.FINALIZING
    assert (await sessions.settle(session_id=session.id)).state is SessionState.SETTLED


async def test_the_database_refuses_a_settled_session_without_a_settlement_time(db, account):
    """A schema guard, like the state CHECK above.

    `settled_at` is what every cost and revenue report keys off. A settled
    session without one is invisible to them while still counting as closed, so
    the invariant is enforced where no code path can route around it.
    """
    with pytest.raises(IntegrityError):
        await db.execute(
            text(
                "INSERT INTO sessions (id, user_id, state, settled_at) "
                "VALUES (:id, :user_id, 'settled', NULL)"
            ),
            {"id": uuid.uuid4(), "user_id": account.user_id},
        )
        await db.commit()


async def test_a_started_session_lands_in_the_audit_trail_atomically(
    sessions, audit, db, account
):
    """The session row and its audit row commit together.

    Recording after the session commit would lose the event whenever the
    process dies in between — and a session with no audit row is exactly the
    one an operator will later be asked to explain.
    """
    session = await sessions.start(user_id=account.user_id)

    events = await audit.events_for_user(user_id=account.user_id)
    assert [event.event_type for event in events] == [AuditEventType.SESSION_STARTED]
    assert events[0].session_id == session.id


async def test_a_refused_start_is_recorded_even_though_nothing_changed(
    sessions, audit, account
):
    """A denial leaves no trace anywhere else.

    The session table shows one live session either way, so without this the
    only evidence that a user was repeatedly refused is an application log line
    that may have been sampled away. CLAUDE.md requires denials to be logged.
    """
    await sessions.start(user_id=account.user_id)

    with pytest.raises(ActiveSessionExists):
        await sessions.start(user_id=account.user_id)

    events = await audit.events_for_user(user_id=account.user_id)
    assert AuditEventType.SESSION_START_DENIED in {event.event_type for event in events}


async def test_a_session_whose_audit_row_fails_to_write_is_not_created_either(
    engine, db, account, monkeypatch
):
    """Proves the shared transaction, which the test above only assumes.

    Asserting that both rows exist passes just as happily when they are written
    by two separate commits. The property that matters is that neither survives
    alone, so this breaks the audit write and checks the session row from a
    *different* connection — the originating one would still see its own
    uncommitted insert and report a row that was never really there.
    """

    def explode(*args, **kwargs):
        raise RuntimeError("audit backend unavailable")

    monkeypatch.setattr(AuditService, "stage", explode)

    # Read before the rollback below. A rollback expires every object in the
    # session even when `expire_on_commit` is off, and touching an expired
    # attribute afterwards triggers a lazy refresh — blocking IO in the middle
    # of an async call, which surfaces as MissingGreenlet rather than anything
    # resembling the real problem.
    user_id = account.user_id

    with pytest.raises(RuntimeError):
        await SessionService(db).start(user_id=user_id)
    await db.rollback()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as observer:
        committed = (
            await observer.execute(
                select(func.count())
                .select_from(SessionModel)
                .where(SessionModel.user_id == user_id)
            )
        ).scalar_one()

    assert committed == 0


async def test_activating_a_session_opens_an_interrogation_span(sessions, account):
    """The meter's structural anchor.

    Metering is not a conditional check scattered across the write paths — the
    ledger references interrogation spans, so "is this billable" is answered by
    which span is open rather than by remembering to ask. A span opening at
    `active` is what makes that answer exist.
    """
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)

    spans = await sessions.spans(session_id=session.id)

    assert [span.phase for span in spans] == [SessionPhase.INTERROGATION]
    assert spans[0].ended_at is None


async def test_finalizing_closes_the_interrogation_span_so_the_meter_stops(
    sessions, account
):
    """The billable window has an end, and it is the same event that stops the
    meter — not a second bookkeeping step that can be forgotten.

    An interrogation span left open is a room that bills forever in every
    replay of the ledger, which is the failure the whole append-only design
    exists to make impossible.
    """
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)

    await sessions.begin_finalizing(session_id=session.id, end_reason=EndReason.USER_ENDED)

    [interrogation] = await sessions.spans(session_id=session.id)
    assert interrogation.ended_at is not None
    assert interrogation.ended_at >= interrogation.started_at


async def test_a_span_survives_the_application_clock_disagreeing_with_the_database(
    sessions, account
):
    """One clock decides when a phase began and ended, and it is the database's.

    In production the API and the database are separate machines. NTP holds
    them within milliseconds of each other, not identical — and a phase can
    close in less time than that gap. Taking `started_at` from the database and
    `ended_at` from the API process therefore compares two clocks inside
    `ck_spans_ordering`, and loses whenever the API's is behind.

    The failure lands during `begin_finalizing`, which is the worst place for
    it: the meter is stopping, and a 500 there leaves the span open — a room
    that bills forever on every replay of the ledger.

    The frozen clock here is an exaggerated skew, not a realistic one. Real
    skew is milliseconds and would make this test pass or fail depending on how
    busy the machine was, which is not a test. Six years makes the same bug
    deterministic.
    """
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)

    with freeze_time("2020-01-01 00:00:00"):
        await sessions.begin_finalizing(
            session_id=session.id, end_reason=EndReason.USER_ENDED
        )
        settled = await sessions.settle(session_id=session.id)

    [interrogation] = await sessions.spans(session_id=session.id)
    assert interrogation.ended_at >= interrogation.started_at

    # `settled_at` has no ordering constraint, so the same mistake here is
    # silent rather than loud: a session that settled six years before it
    # started, sitting in the table looking like data. It feeds cost reporting
    # and any future billing dispute, which are the two places nobody wants to
    # discover the clock was wrong.
    assert settled.settled_at >= settled.started_at


async def test_debrief_opens_on_a_settled_session_and_bills_nothing(
    sessions, ledger, account
):
    """The metering boundary, structurally (Product.md §4.1).

    Debrief and sparring are the part §3.5 calls "what users will pay for", and
    they are unmetered. Opening one on a *settled* session is the normal case,
    not an exception: billing closed when the room did, and the coaching that
    follows is deliberately free — including for a user who came back to it an
    hour later.
    """
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await sessions.begin_finalizing(session_id=session.id, end_reason=EndReason.USER_ENDED)
    await sessions.settle(session_id=session.id)

    await sessions.open_phase(session_id=session.id, phase=SessionPhase.DEBRIEF)

    spans = await sessions.spans(session_id=session.id)
    assert [span.phase for span in spans] == [
        SessionPhase.INTERROGATION,
        SessionPhase.DEBRIEF,
    ]
    assert await ledger.entries(user_id=account.user_id) == []


async def test_the_meter_cannot_be_restarted_by_opening_an_interrogation_phase(
    sessions, account
):
    """The coaching door does not open a billable phase.

    `open_phase` is the one call that exists to be used *after* settlement, so
    it is exactly where a mistake would restart the meter on a session already
    paid for and forgiven. Interrogation spans come from `activate` alone, which
    means the state machine's transition table is the only way to reach a
    billable window — the metering boundary cannot be routed around by picking a
    different method.
    """
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await sessions.begin_finalizing(session_id=session.id, end_reason=EndReason.USER_ENDED)
    await sessions.settle(session_id=session.id)

    with pytest.raises(InvalidStateTransition):
        await sessions.open_phase(
            session_id=session.id, phase=SessionPhase.INTERROGATION
        )

    assert len(await sessions.spans(session_id=session.id)) == 1


async def test_devices_racing_to_open_a_phase_produce_one_span(engine, db, account):
    """One open span per session, arbitrated by Postgres.

    Two open spans double-count the phase in the §4.3 per-phase durations, and
    for interrogation that is a double charge for one stretch of wall-clock
    time. The service closes the open span before inserting, but that check
    cannot see an uncommitted sibling transaction — the same reason the
    one-live-session rule is an index rather than a query.

    Losing this race is not an error. Both devices wanted the user in debrief
    and nothing is billed either way, so the loser is handed the span that won
    rather than a 409 for a phase that costs nothing.

    Connections are established before the race for the reason documented on
    the start race above: a cold pool serializes the racers and the test passes
    without proving anything.
    """
    session = await SessionService(db).start(user_id=account.user_id)
    await SessionService(db).activate(session_id=session.id)
    await SessionService(db).begin_finalizing(
        session_id=session.id, end_reason=EndReason.USER_ENDED
    )
    await SessionService(db).settle(session_id=session.id)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    racers = [factory() for _ in range(5)]
    await asyncio.gather(*(racer.execute(text("SELECT 1")) for racer in racers))

    gate = asyncio.Event()

    async def open_once(racer):
        await gate.wait()
        return await SessionService(racer).open_phase(
            session_id=session.id, phase=SessionPhase.DEBRIEF
        )

    tasks = [asyncio.create_task(open_once(racer)) for racer in racers]
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(*tasks)

    for racer in racers:
        await racer.close()

    assert len({result.id for result in results}) == 1

    open_spans = (
        await db.execute(
            select(func.count())
            .select_from(SessionPhaseSpan)
            .where(
                SessionPhaseSpan.session_id == session.id,
                SessionPhaseSpan.ended_at.is_(None),
            )
        )
    ).scalar_one()
    assert open_spans == 1


async def test_moving_from_debrief_to_sparring_keeps_the_two_durations_apart(
    sessions, account
):
    """§4.3 needs `debrief_seconds` and `sparring_seconds` separately.

    It admits its median coaching duration is a guess, and the only way to
    replace that guess with a measurement is for each phase to have its own
    closed span. Opening sparring without closing debrief would leave one merged
    blob that answers neither question.
    """
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await sessions.begin_finalizing(session_id=session.id, end_reason=EndReason.USER_ENDED)
    await sessions.settle(session_id=session.id)

    await sessions.open_phase(session_id=session.id, phase=SessionPhase.DEBRIEF)
    await sessions.open_phase(session_id=session.id, phase=SessionPhase.SPARRING)

    spans = await sessions.spans(session_id=session.id)
    assert [span.phase for span in spans] == [
        SessionPhase.INTERROGATION,
        SessionPhase.DEBRIEF,
        SessionPhase.SPARRING,
    ]
    assert [span.ended_at is None for span in spans] == [False, False, True]


async def test_coaching_cannot_open_while_the_room_is_still_running(sessions, account):
    """Billing closes before coaching opens, in that order.

    Opening a coaching phase closes whatever span is open, so allowing it during
    an `active` session would stop the meter through a door that was never meant
    to touch billing — leaving a session that is still `active`, still holding
    the lock, with no open span for the ledger to attach a tick to. §4.1 orders
    it the other way: let the panel finish, settle, *then* hand off to debrief.
    """
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)

    with pytest.raises(InvalidStateTransition):
        await sessions.open_phase(session_id=session.id, phase=SessionPhase.DEBRIEF)

    [interrogation] = await sessions.spans(session_id=session.id)
    assert interrogation.ended_at is None


async def test_a_full_lifecycle_reads_as_a_story_in_the_audit_trail(sessions, audit, account):
    """What an operator actually reads during a dispute.

    Each transition is written where it happens rather than reconstructed later
    from timestamps, because `settled` alone cannot say *why* a session ended —
    a user finishing and a provider dying leave identical rows otherwise.
    """
    session = await sessions.start(user_id=account.user_id)
    await sessions.activate(session_id=session.id)
    await sessions.begin_finalizing(
        session_id=session.id, end_reason=EndReason.PROVIDER_FAILURE
    )
    await sessions.settle(session_id=session.id)

    events = await audit.events_for_user(user_id=account.user_id)
    # Most recent first, as an operator reads backwards from the incident.
    assert [event.event_type for event in events] == [
        AuditEventType.SESSION_SETTLED,
        AuditEventType.SESSION_STARTED,
    ]
    assert events[0].context["end_reason"] == EndReason.PROVIDER_FAILURE.value
