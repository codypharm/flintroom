"""What a room spent, recorded as it spends it.

`SessionCost` has carried a column for each vendor since Phase 2 and settlement
filled none of them — it wrote the room's duration and a hardcoded
`agent_session_count=1`. That was very nearly enough when a room was one agent
on one opaque per-minute rate. It is not enough now: a turn bills the
transcriber by the second, the panel model by the token and synthesis by the
character, and Open Risk #4 says every margin in `Product.md` §4.4 rests on an
unverified $0.12/min that nothing in the system could contradict.

Written per turn rather than at settlement, because a session whose process dies
is settled by the reaper, which never held the channel. Anything kept in memory
would be lost for exactly the rooms where cost and revenue diverge most.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.sessions.schemas import EndReason
from app.modules.sessions.service import SessionService

from tests.test_session_costs import _running_for
from app.modules.voice.costs import SessionCost
from app.modules.voice.spend import SpendRecorder

pytestmark = pytest.mark.asyncio


async def _cost(db, session_id) -> SessionCost | None:
    return await db.scalar(
        select(SessionCost).where(SessionCost.session_id == session_id)
    )


async def test_a_turn_leaves_a_record_of_what_it_cost(db, funded_account):
    """The row exists from the first turn, not from settlement.

    A room that crashes mid-interrogation has already been billed by three
    providers. If the only write happened at settlement, the reaper — which
    never held the channel — would settle it with nothing, and the most
    expensive rooms in the product would be the ones recorded as free.
    """
    session = await SessionService(db).start(user_id=funded_account.user_id)

    await SpendRecorder(db).record(
        session_id=session.id,
        stt_seconds=4,
        llm_input_tokens=812,
        llm_output_tokens=31,
        tts_characters=147,
    )

    cost = await _cost(db, session.id)
    assert cost is not None
    assert cost.stt_seconds_processed == 4
    assert cost.llm_input_tokens == 812
    assert cost.llm_output_tokens == 31
    assert cost.tts_characters_synthesized == 147


async def test_turns_accumulate_rather_than_overwrite(db, funded_account):
    """A room is the sum of its turns, and the second must not erase the first.

    An upsert that replaced instead of adding would record only the last turn,
    so every room would look like a one-question room — and the error would grow
    with exactly the sessions that went well.
    """
    session = await SessionService(db).start(user_id=funded_account.user_id)
    recorder = SpendRecorder(db)

    await recorder.record(
        session_id=session.id,
        stt_seconds=4, llm_input_tokens=800, llm_output_tokens=30, tts_characters=100,
    )
    await recorder.record(
        session_id=session.id,
        stt_seconds=6, llm_input_tokens=900, llm_output_tokens=25, tts_characters=120,
    )

    cost = await _cost(db, session.id)
    assert cost.stt_seconds_processed == 10
    assert cost.llm_input_tokens == 1_700
    assert cost.llm_output_tokens == 55
    assert cost.tts_characters_synthesized == 220


async def test_settlement_completes_a_row_the_turns_already_started(
    db, sessions, settlement, meter, funded_account
):
    """Two writers, different columns, and neither may erase the other.

    Settlement owns the duration and the tier; turns own the consumption. Its
    insert was `on_conflict_do_nothing`, which was right while it was the only
    writer and is wrong now — the row exists before the room ends for every
    session in which anybody spoke, so doing nothing would silently discard the
    interrogation seconds of every real interrogation and keep them only for
    rooms where the panel never said a word.

    That failure would be close to invisible: the table would fill up, the rows
    would look plausible, and the denominator of every per-minute figure would
    be zero for exactly the sessions worth measuring.
    """
    session = await sessions.start(user_id=funded_account.user_id)
    await sessions.activate(session_id=session.id)
    await SpendRecorder(db).record(
        session_id=session.id,
        stt_seconds=4, llm_input_tokens=800, llm_output_tokens=30, tts_characters=100,
    )

    await _running_for(db, session, seconds=60)
    await meter.sweep()
    await settlement.close(session_id=session.id, end_reason=EndReason.USER_ENDED)

    cost = await _cost(db, session.id)
    assert cost.llm_input_tokens == 800
    assert cost.interrogation_seconds >= 60
    assert cost.tier == "free"



async def test_a_turn_prices_itself(db, funded_account):
    """`computed_cost_usd` has been declared since Phase 2 and null on every row.

    Open Risk #4 says every margin in §4.4 rests on an unverified $0.12/min that
    nothing in the system could contradict — and it could not, because the one
    column that would have contradicted it was never written. The rates are
    published rather than invoiced (#14 is the invoice), which is enough for the
    daily ceiling this unblocks and not yet enough to move a price.
    """
    session = await SessionService(db).start(user_id=funded_account.user_id)

    await SpendRecorder(db).record(
        session_id=session.id,
        stt_seconds=50,
        llm_input_tokens=2_495,
        llm_output_tokens=80,
        tts_characters=371,
    )

    cost = await _cost(db, session.id)
    # One measured interrogation minute, which `docs/voice-cost.md` puts at
    # ~$0.046 across 17 real rooms.
    assert cost.computed_cost_usd is not None
    assert Decimal("0.044") < cost.computed_cost_usd < Decimal("0.048")


async def test_the_price_accumulates_with_the_turns(db, funded_account):
    """Added, never recomputed-and-replaced.

    Cost is linear in usage, so adding each turn's price gives the same answer
    as pricing the total — and it keeps the addition inside the statement, which
    is what stops two writers reading the same total and each adding to it.
    """
    session = await SessionService(db).start(user_id=funded_account.user_id)
    recorder = SpendRecorder(db)

    await recorder.record(session_id=session.id, tts_characters=371)
    first = (await _cost(db, session.id)).computed_cost_usd
    await recorder.record(session_id=session.id, tts_characters=371)

    cost = await _cost(db, session.id)
    assert cost.computed_cost_usd == first * 2


async def test_a_room_that_only_opened_its_mouth_is_not_free(db, funded_account):
    """The correction #73 exists to make.

    `docs/voice-cost.md` priced a room abandoned under one tick at $0.0016 with
    "panel speech: none — nobody spoke". True when the presenter held the floor
    in silence; #79 gave the room a spoken opener that fires before anything is
    transcribed, and the doc named that exact reopen condition.

    So the cheapest room in the product is several times cheaper than a real one
    and several times more expensive than the doc records.
    """
    session = await SessionService(db).start(user_id=funded_account.user_id)

    await SpendRecorder(db).record(
        session_id=session.id, stt_seconds=15, tts_characters=35
    )

    cost = await _cost(db, session.id)
    assert cost.computed_cost_usd > Decimal("0.004")
