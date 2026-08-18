"""What the unmetered phases actually spend.

§4.3 calls these the model's largest uncontrolled exposure and gives
`session_costs` two columns for them. Both have existed since Phase 2 and
neither has ever been written, because the mechanism they were designed around
— a phase span with a start and an end — was never wired for coaching.

Turn-based transport (`docs/debrief-and-sparring.md` decision 5) made the span
the wrong instrument rather than an unfinished one. There is no socket to hold
open, so nothing bills for silence, and cost is per turn. Duration is a
different question and the turn timestamps already answer it.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update

from app.agents.coach import Cite, CoachReply
from app.agents.context import USER, Said
from app.agents.model import TurnUsage
from app.modules.sessions.models import CoachTurn, SparringAttempt
from app.modules.voice.costs import SessionCost

from tests.test_coaching import (
    ROOM,
    ScriptedCoach,
    ScriptedDictation,
    SparringCoach,
    coaching,
    debriefed,
)


async def cost_row(db, session_id) -> SessionCost | None:
    rows = await db.execute(
        select(SessionCost).where(SessionCost.session_id == session_id)
    )
    return rows.scalar_one_or_none()


async def test_a_coaching_turn_reports_what_it_spent(
    db, engine, sessions, settlement, funded_account
):
    """Every vendor on the path, on the row §4.3 reconciles against an invoice.

    A coaching turn pays three of them — the transcriber hears the clip, the
    model answers, the synthesiser speaks — and the phase earns nothing. That is
    the whole reason `docs/ingestion.md`'s framing applies here too: unmetered is
    not free, and a phase whose cost nobody counted is the one that quietly
    decides a margin.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    coach = ScriptedCoach(
        CoachReply(
            text="The CFO wanted a base.",
            cites=(Cite(kind="line", index=1),),
            usage=TurnUsage(900, 120),
        )
    )

    await coaching(db, coach=coach, dictation=ScriptedDictation("Why?")).say(
        session_id=session.id, clip=b"one", media_type="audio/wav"
    )

    cost = await cost_row(db, session.id)
    assert cost is not None
    assert cost.llm_input_tokens == 900
    assert cost.llm_output_tokens == 120
    assert cost.stt_seconds_processed == 3
    assert cost.tts_characters_synthesized == len("The CFO wanted a base.")


async def test_a_second_turn_adds_rather_than_replaces(
    db, engine, sessions, settlement, funded_account
):
    """A debrief is the sum of its turns.

    An upsert that overwrote would record only the last one, so every session
    would look like a single-question debrief — and the error would grow with
    precisely the conversations that went well and ran longest.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    service = coaching(db, dictation=ScriptedDictation("Why?"))

    await service.say(session_id=session.id, clip=b"one", media_type="audio/wav")
    await service.say(session_id=session.id, clip=b"two", media_type="audio/wav")

    cost = await cost_row(db, session.id)
    assert cost.stt_seconds_processed == 6


async def test_how_long_they_stayed_is_measured_from_the_turns(
    db, engine, sessions, settlement, funded_account
):
    """The number §4.3 asks for by name, and the one the soft cap rests on.

    "Also measure: median unmetered coaching duration. The ~10-minute average in
    §4.3 is a guess, and unmetered time is the model's largest uncontrolled
    exposure. If the real median runs past 20 minutes, the soft cap in §4.7
    needs tightening."

    Measured from the first coaching turn to the last rather than from a phase
    span, because no span is opened: with no socket there is nothing to open one
    around, and one opened on a debrief read would never be closed and would
    grow without bound. An unbounded number is worse than a missing one — a
    wrong number gets fixed, and an unbounded one gets averaged into a price.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    service = coaching(db, dictation=ScriptedDictation("Why?"))

    await service.say(session_id=session.id, clip=b"one", media_type="audio/wav")

    # Their first turn, six minutes ago. Backdated rather than slept through.
    await db.execute(
        update(CoachTurn)
        .where(CoachTurn.session_id == session.id, CoachTurn.ordinal == 0)
        .values(said_at=CoachTurn.said_at - timedelta(minutes=6))
    )
    await db.commit()

    await service.say(session_id=session.id, clip=b"two", media_type="audio/wav")

    cost = await cost_row(db, session.id)
    assert 340 <= cost.debrief_seconds <= 380


async def test_sparring_is_counted_inside_the_debrief_not_beside_it(
    db, engine, sessions, settlement, funded_account
):
    """The two columns overlap, and that has to be said out loud.

    With turn-based transport there is no moment where somebody leaves the
    debrief and enters sparring — a re-try is a turn among turns. So
    `debrief_seconds` is the whole coaching engagement and `sparring_seconds` is
    the subset spent re-answering. **They must never be summed**; doing so would
    double-count the same minutes and inflate the one figure §4.3 uses to decide
    whether the soft cap is tight enough.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    service = coaching(
        db, coach=SparringCoach(), dictation=ScriptedDictation("Two million ARR.")
    )

    await service.spar(
        session_id=session.id, weak_rank=0, clip=b"one", media_type="audio/wav"
    )

    # Backdate the attempt so the span is a real number rather than zero.
    # Written after the first version of this test passed against a feature
    # that did not exist: `settlement.close` already leaves a costs row with
    # zero defaults, so `is not None` and `0 >= 0` were both true and the
    # assertion proved nothing.
    await db.execute(
        update(SparringAttempt)
        .where(SparringAttempt.session_id == session.id)
        .values(said_at=SparringAttempt.said_at - timedelta(minutes=4))
    )
    await db.commit()

    await service.spar(
        session_id=session.id, weak_rank=0, clip=b"two", media_type="audio/wav"
    )

    cost = await cost_row(db, session.id)
    assert 220 <= cost.sparring_seconds <= 260
    assert cost.debrief_seconds >= cost.sparring_seconds


async def test_a_redirected_turn_is_billed_for_what_was_actually_spoken(
    db, engine, sessions, settlement, funded_account
):
    """The synthesiser is paid for the redirect, so the redirect is the count.

    A turn the fence replaced never reaches the voice provider as the text the
    model wrote — `spoken` swapped it before synthesis. Billing the intended
    text would misreport every redirected turn, and always in the same
    direction, because the redirect is a fixed string and the thing it replaced
    is not.

    Written after a mutation survived: swapping `said` for `reply.text` in the
    cost call passed every other test in this file, because none of them
    redirect.
    """
    session = await debriefed(db, engine, sessions, settlement, funded_account, *ROOM)
    coach = ScriptedCoach(
        CoachReply(
            text="Your new deck looks strong, and the market timing is good.",
            cites=(Cite(kind="line", index=99),),
            usage=TurnUsage(900, 120),
        )
    )

    turn = await coaching(db, coach=coach).say(
        session_id=session.id, clip=b"one", media_type="audio/wav"
    )

    cost = await cost_row(db, session.id)
    assert cost.tts_characters_synthesized == len(turn.text)
    assert cost.tts_characters_synthesized != len(
        "Your new deck looks strong, and the market timing is good."
    )
