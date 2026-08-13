"""Cost telemetry — the row that decides whether the pricing survives.

Every figure in `Product.md` §4.4–4.5 rests on one unverified assumption: that
interrogation costs about $0.12/min because only one panelist speaks at a time.
§4.3 is explicit that if ElevenLabs bills per active agent session rather than
per synthesized minute, that assumption is wrong and every tier margin
collapses.

`agent_session_count` is the column that settles it, which is why §4.3 requires
this table to ship *with* the first working voice loop rather than after it —
cost visibility has to exist before the first ten test sessions, not once
somebody wonders why the invoice looks like that.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select, update

from app.modules.sessions.models import Session as SessionModel
from app.modules.sessions.models import SessionPhaseSpan
from app.modules.sessions.schemas import EndReason, SessionState
from app.modules.voice.costs import SessionCost


async def _running_for(db, session, *, seconds: int) -> None:
    await db.execute(
        update(SessionPhaseSpan)
        .where(
            SessionPhaseSpan.session_id == session.id,
            SessionPhaseSpan.ended_at.is_(None),
        )
        .values(started_at=func.now() - timedelta(seconds=seconds))
    )
    await db.commit()


async def _cost_row(db, session_id) -> SessionCost | None:
    result = await db.execute(
        select(SessionCost).where(SessionCost.session_id == session_id)
    )
    return result.scalar_one_or_none()


async def test_a_settled_room_leaves_a_cost_row(
    db, sessions, settlement, meter, funded_account
):
    """One row per session, written when the room closes.

    At settlement rather than during the room, because this is the point where
    the interrogation window is final. A row accumulated live would have to be
    corrected by every refund and every grace write-off, and a cost report
    reconciled against an invoice cannot afford a figure that was true at some
    point during the session.

    The seconds recorded are the metered window, not wall-clock from `start`:
    spin-up time is real latency but it is not interrogation, and billing and
    costing have to be counted from the same mark or the margin is measured
    against the wrong denominator.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await sessions.activate(session_id=session.id)

    await _running_for(db, session, seconds=60)
    await meter.sweep()
    await settlement.close(session_id=session.id, end_reason=EndReason.USER_ENDED)

    cost = await _cost_row(db, session.id)
    assert cost is not None
    assert cost.user_id == funded_account.user_id
    assert cost.tier == "free"
    assert cost.interrogation_seconds >= 60
    # One agent for one room, until the panel arrives in Phase 3. The column
    # exists now precisely so the number is observed rather than assumed.
    assert cost.agent_session_count == 1


async def test_a_settlement_that_runs_twice_costs_the_session_once(
    db, sessions, settlement, meter, funded_account
):
    """The reaper retries a settlement that died partway. It must not re-cost.

    Settlement writes several rows and can die between them, which is why
    `finalizing` exists at all — it is what separates "finished settling" from
    "died halfway" so the reaper can safely run it again. Everything else
    settlement writes is idempotent; this row has to be too.

    A second row would not fail loudly. It would quietly double one session in
    every per-minute average computed from this table, which is precisely the
    figure §4.3 says pricing may not ship without.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await sessions.activate(session_id=session.id)
    await _running_for(db, session, seconds=60)
    await meter.sweep()
    await settlement.close(session_id=session.id, end_reason=EndReason.USER_ENDED)

    # Rewound to the state a half-finished settlement leaves behind: the meter
    # stopped and the end reason recorded, but the session never marked settled.
    await db.execute(
        update(SessionModel)
        .where(SessionModel.id == session.id)
        .values(state=SessionState.FINALIZING, settled_at=None)
    )
    await db.commit()

    await settlement.settle(session_id=session.id)

    rows = await db.execute(
        select(func.count())
        .select_from(SessionCost)
        .where(SessionCost.session_id == session.id)
    )
    assert rows.scalar_one() == 1


async def test_a_room_that_never_opened_is_not_costed(
    db, sessions, funded_account
):
    """A failed spin-up is not a session, and must not appear as one.

    `provisioning` and `failed` exist so a room that never opened is
    distinguishable in every query and every cost report. A zero-second row
    here would put it back into the denominator — dragging the observed cost
    per interrogation minute down by exactly the sessions that produced no
    interrogation at all.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await sessions.fail(session_id=session.id)

    assert await _cost_row(db, session.id) is None
