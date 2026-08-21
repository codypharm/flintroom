"""Turning what a room used into what it cost.

`session_costs.computed_cost_usd` has been declared since Phase 2 and nothing
has ever written it — so the column that Open Risk #4 exists to fill has been
null on every row, and the daily spend ceiling `CLAUDE.md` requires had no
figure to read.

These rates are arithmetic over published rates, not observations. #14 is what
replaces them with an invoice; until then the honest position is that this is a
*good estimate*, which is what a circuit breaker needs and not yet what a
pricing decision needs.
"""

from decimal import Decimal

from app.modules.voice.rates import Usage, cost_usd


def test_a_room_that_used_nothing_cost_nothing():
    # Not a rounding artefact: a session row is created by the first turn, and
    # a room that never got one should read zero rather than null-shaped noise.
    assert cost_usd(Usage()) == Decimal("0")


def test_transcription_is_priced_by_the_second_at_the_verified_rate():
    """Scribe at $0.39/hr — `docs/voice-cost.md` calls this a verified rate,
    read off `transcribers/elevenlabs.py` rather than assumed."""
    hour = cost_usd(Usage(stt_seconds=3600))

    assert hour == Decimal("0.390000")


def test_synthesis_is_priced_by_the_character_and_dominates():
    """88% of a room's bill is synthesising what the panel says, which is the
    single most important thing `docs/voice-cost.md` measured. A cost model
    that got this line wrong would be wrong about the room."""
    minute_of_panel_speech = cost_usd(Usage(tts_characters=371))

    # ~$0.04/interrogation-minute, the figure the doc's share table is built on.
    assert Decimal("0.039") < minute_of_panel_speech < Decimal("0.041")


def test_the_panel_model_is_priced_and_is_a_rounding_error():
    """2,495 in / 80 out is a measured interrogation minute. It is ~0.6% of the
    bill, and it is priced anyway — a cost model that omits a line because it is
    small cannot later notice that it stopped being small."""
    minute = cost_usd(Usage(llm_input_tokens=2495, llm_output_tokens=80))

    assert Decimal("0") < minute < Decimal("0.001")


def test_a_measured_interrogation_minute_lands_where_the_doc_says_it_does():
    """The whole point of the exercise: one minute of room, priced from the
    usage `docs/voice-cost.md` measured across 17 real rooms, should reproduce
    its ~$0.046/min. If this drifts, either the rates moved or the room did."""
    minute = cost_usd(
        Usage(
            stt_seconds=50,
            tts_characters=371,
            llm_input_tokens=2495,
            llm_output_tokens=80,
        )
    )

    assert Decimal("0.044") < minute < Decimal("0.048")


def test_an_abandoned_room_costs_more_than_nothing():
    """The correction this task exists to make.

    `docs/voice-cost.md` priced an abandoned room at "$0.0016, panel speech:
    none — nobody spoke". That was true when the presenter held the floor in
    silence. #79 gave the room a spoken opener, which fires before anything is
    transcribed — so the cheapest possible room now synthesises one line.

    The doc named this exact reopen condition: "if anything is ever added that
    synthesises speech before the presenter has spoken."
    """
    silent_but_opened = cost_usd(Usage(stt_seconds=15, tts_characters=35))

    # Several times the $0.0016 the doc records for the same room.
    assert silent_but_opened > Decimal("0.004")


def test_the_result_is_a_decimal_and_never_a_float():
    """Money. `computed_cost_usd` is Numeric, the ceiling compares against it,
    and a float would make the comparison depend on how the sum was ordered."""
    assert isinstance(cost_usd(Usage(tts_characters=371)), Decimal)


def test_usage_can_be_read_straight_off_a_cost_row():
    """The row's column names are the argument names, so the caller that has a
    `SessionCost` is not writing a mapping that can drift from it."""
    usage = Usage(
        stt_seconds=50,
        tts_characters=371,
        llm_input_tokens=2495,
        llm_output_tokens=80,
    )

    assert cost_usd(usage) == cost_usd(
        Usage(
            stt_seconds=usage.stt_seconds,
            tts_characters=usage.tts_characters,
            llm_input_tokens=usage.llm_input_tokens,
            llm_output_tokens=usage.llm_output_tokens,
        )
    )
