"""How the panel is receiving the argument, read from what the room already did.

`Product.md` §3.4 asks for a directional read; `CLAUDE.md` fixes the vocabulary
as neutral and transferable — Convinced / Skeptical / Losing the room — and
forbids the retired investor scale.

**No model call, and the reason is a measurement rather than a preference.**
Asked *"did the presenter dodge?"* a model said yes on 4 of 4 dodges and 4 of 4
genuine answers (#43), which `agents/difficulty.py` already cites as the ground
for making that dial two integers. A gauge is the same question in a friendlier
coat, and it would be asked eight to fifteen times a room on the metered path.
"""

from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import USER, Said
from app.agents.temperature import (
    CAUGHT_TO_COOL,
    CLEAN_TO_WARM,
    WINDOW,
    Temperature,
    temperature_of,
)
from app.modules.voice.provider import VoiceProvider
from app.modules.voice.relay import VoiceRelay
from tests.fakes import FakeClientChannel


def said(*, by: str = "cfo", caught: bool = False, disputed: bool = False) -> Said:
    return Said(
        speaker=by,
        text="Off what base, and at what cost?",
        disputed=disputed,
        chosen_by="finding" if caught else "model",
    )


def answer() -> Said:
    return Said(speaker=USER, text="Off a base of two hundred accounts.")


def room(*lines: Said) -> list[Said]:
    """A transcript with the presenter answering between every challenge."""
    woven: list[Said] = []
    for line in lines:
        woven.extend([line, answer()])
    return woven


def read(*lines: Said, was: Temperature = Temperature.SKEPTICAL) -> Temperature:
    return temperature_of(room(*lines), was=was)


class TestOpening:
    def test_a_room_that_has_barely_started_reads_neutral(self) -> None:
        # Skeptical is the resting value rather than a fourth "unknown" band,
        # and that is the product being honest: a panel opens unconvinced. It
        # is also what lets the screen open in its resting state.
        assert read(said(), said()) is Temperature.SKEPTICAL

    def test_an_empty_room_reads_neutral(self) -> None:
        assert temperature_of([], was=Temperature.SKEPTICAL) is Temperature.SKEPTICAL

    def test_the_presenter_talking_alone_is_not_a_reading(self) -> None:
        # The opening floor (#79) is the presenter making their case before
        # anybody challenges it. Nothing has been received yet.
        assert temperature_of([answer(), answer(), answer()], was=Temperature.SKEPTICAL) is (
            Temperature.SKEPTICAL
        )


class TestCooling:
    def test_being_caught_twice_in_the_window_loses_the_room(self) -> None:
        # `chosen_by == "finding"` is the Auditor having caught the answer
        # before this line — a figure that moved, or a claim that contradicts
        # one made earlier in the same room. It is the one signal here that is
        # an event rather than an absence.
        assert (
            read(said(caught=True), said(), said(), said(caught=True))
            is Temperature.LOSING
        )

    def test_being_caught_once_is_not_yet_losing_the_room(self) -> None:
        # Everybody gets a figure wrong. Telling somebody they are losing the
        # room over one is the failure this gauge must not have, because they
        # cannot argue with it mid-session.
        assert read(said(), said(caught=True), said(), said()) is Temperature.SKEPTICAL

    def test_two_catches_outside_the_window_have_passed(self) -> None:
        # A room that was going badly and recovered is a room that recovered.
        assert (
            read(
                said(caught=True),
                said(caught=True),
                said(),
                said(),
                said(),
                said(),
                was=Temperature.SKEPTICAL,
            )
            is not Temperature.LOSING
        )


class TestWarming:
    def test_a_long_clean_run_convinces_them(self) -> None:
        assert read(*[said() for _ in range(CLEAN_TO_WARM)]) is Temperature.CONVINCED

    def test_warming_asks_for_more_than_cooling(self) -> None:
        # Deliberately asymmetric. Being caught is evidence; not being caught is
        # the absence of it, and absence is cheap early in a deckless room where
        # the Auditor's reference is still the transcript accumulating
        # (`docs/auditor-grounding.md`). So a clean run has to be longer than a
        # bad one is wide before the room says anything encouraging.
        assert CLEAN_TO_WARM > CAUGHT_TO_COOL
        assert read(*[said() for _ in range(CLEAN_TO_WARM - 1)]) is Temperature.SKEPTICAL

    def test_one_catch_anywhere_in_the_run_is_not_a_clean_run(self) -> None:
        lines = [said() for _ in range(CLEAN_TO_WARM)]
        lines[2] = said(caught=True)

        assert read(*lines) is not Temperature.CONVINCED


class TestHysteresis:
    def test_a_losing_room_stays_lost_while_a_catch_is_still_in_the_window(self) -> None:
        # Two clean turns after being caught twice is not a recovery, and a
        # gauge that said so would flip on alternate turns for the rest of the
        # room. The window still holds one catch, so the room is still lost.
        assert (
            read(
                said(caught=True),
                said(caught=True),
                said(),
                said(),
                said(),
                was=Temperature.LOSING,
            )
            is Temperature.LOSING
        )

    def test_a_clear_window_lets_a_losing_room_back_to_neutral(self) -> None:
        assert (
            read(
                said(caught=True),
                said(caught=True),
                *[said() for _ in range(WINDOW)],
                was=Temperature.LOSING,
            )
            is Temperature.SKEPTICAL
        )

    def test_it_never_jumps_between_the_two_extremes(self) -> None:
        # Every route between Convinced and Losing passes through Skeptical, so
        # the safelight always crosses neutral rather than swinging. Two moves
        # to go from convinced to losing is also what keeps a twelve-minute room
        # to two or three changes rather than one per turn.
        convinced = [said() for _ in range(CLEAN_TO_WARM)]
        assert read(*convinced) is Temperature.CONVINCED

        caught = [*convinced, said(caught=True), said(caught=True)]
        assert read(*caught, was=Temperature.CONVINCED) is Temperature.SKEPTICAL

    def test_a_convinced_room_cools_on_the_first_catch(self) -> None:
        # Asymmetric again, the other way round. Warming is slow because it is
        # an absence; cooling off "convinced" is fast because the room has just
        # been shown a thing it got wrong, and going on claiming the panel is
        # persuaded would be the gauge arguing with what they just heard.
        convinced = [said() for _ in range(CLEAN_TO_WARM)]

        assert (
            read(*convinced, said(caught=True), was=Temperature.CONVINCED)
            is Temperature.SKEPTICAL
        )


class TestDisputes:
    def test_a_colleague_cutting_across_is_not_the_presenter_losing_the_room(self) -> None:
        # #56's rule, applied here. A question waved away by another panelist is
        # unanswered and not the presenter's fault, and the debrief already
        # refuses to rank it against them. A gauge that cooled on it would be
        # telling somebody they are losing a room they were not allowed to
        # answer in.
        disputed = [said(disputed=True) for _ in range(CLEAN_TO_WARM + 2)]

        assert read(*disputed) is Temperature.SKEPTICAL

    def test_disputes_do_not_pad_a_clean_run_either(self) -> None:
        # Excluded, not counted as good. Otherwise a room that argued with
        # itself twice would warm on turns the presenter never spoke in.
        run = [said() for _ in range(CLEAN_TO_WARM - 2)]

        assert read(*run, said(disputed=True), said(disputed=True)) is Temperature.SKEPTICAL


class TestWhatItCosts:
    def test_it_is_a_pure_function_of_lines_the_room_already_wrote(self) -> None:
        # The guard against the obvious implementation. Nothing here may call a
        # provider: this is derived eight to fifteen times per room on the
        # metered path, and §4.3's margins are already unverified.
        lines = room(said(), said(caught=True), said())

        first = temperature_of(lines, was=Temperature.SKEPTICAL)
        again = temperature_of(lines, was=Temperature.SKEPTICAL)

        assert first is again
        assert lines == room(said(), said(caught=True), said())


@pytest.mark.asyncio
class TestOnTheWire:
    """It reaches the phone, or it is a value nobody can see.

    The safelight is the *only* place this lands (the interrogation brief), and
    the phone cannot derive it: `chosen_by` never goes over the socket, and it
    would be the wrong thing to send — a routing reason is internal, and a
    client free to interpret one would be free to draw a different room from the
    one the server read.
    """

    async def test_the_relay_carries_it_to_the_client(self) -> None:
        import uuid

        from app.modules.voice.events import RoomTemperature

        client = FakeClientChannel()
        relay = _relay_with(client)

        await relay._handle(
            RoomTemperature(Temperature.LOSING), session_id=uuid.uuid4()
        )

        # The wire value, not the enum. `losing_the_room` is the vocabulary
        # `CLAUDE.md` fixed, and a shorter word would let a client render a
        # sentence the product does not say.
        assert client.temperatures == ["losing_the_room"]

    async def test_it_is_named_in_the_union_every_consumer_matches_on(self) -> None:
        # `test_voice_events.py` enforces this by inspection for every event, and
        # the property it protects is worth restating where the event is built:
        # a room can send something the union does not name, and nothing
        # anywhere errors — the union just quietly stops describing reality.
        import typing

        from app.modules.voice import events

        assert events.RoomTemperature in typing.get_args(events.VoiceEvent)


def _relay_with(client: FakeClientChannel) -> VoiceRelay:
    """A relay with nothing behind it but the client.

    Handling a temperature touches no database and no provider — the event
    carries no session state of its own, exactly like `Attending`, and the
    relay's whole job for it is that the phone hears it. Wiring a session
    fixture in would make this a test about fixtures.
    """
    return VoiceRelay(
        cast(AsyncSession, None), provider=cast(VoiceProvider, None), client=client
    )


@pytest.mark.asyncio
class TestWhatTheRoomSends:
    """When the safelight is told, and how often.

    The two failures #74 names are opposite and both real: a gauge that twitches
    every turn is noise, and one that moves twice a room is not feedback. What
    settles it is that the *bands* are hysteretic (see above) while the *sending*
    is not clever — transitions go out immediately, and the heartbeat repeats
    whatever is true, so a phone that dropped one message is wrong for one beat
    rather than for the rest of the room.
    """

    async def test_the_room_says_how_it_is_receiving_before_anyone_speaks(self) -> None:
        # A safelight with no value would be the screen's ambient ground picking
        # its own colour until the first turn landed — on the one surface whose
        # whole premise is that nobody looks directly at it.
        from tests.test_orchestrated_channel import (
            FakeTranscription,
            ScriptedPanelModel,
            events_of,
        )
        from app.agents.archetypes import DEFAULT_PANEL
        from app.agents.context import Grounding
        from app.modules.voice.events import RoomTemperature
        from app.modules.voice.orchestrated import OrchestratedChannel

        channel = OrchestratedChannel(
            panel=DEFAULT_PANEL,
            transcription=FakeTranscription([]),
            model=ScriptedPanelModel(),
            grounding=Grounding(),
        )

        events = await events_of(channel)
        read = [event for event in events if isinstance(event, RoomTemperature)]

        assert read != []
        assert read[0].state is Temperature.SKEPTICAL

    async def test_it_does_not_repeat_itself_turn_after_turn(self) -> None:
        # The room opens neutral and a handful of ordinary turns keep it there,
        # so a channel that sent one per turn would be sending the same word
        # eight to fifteen times to say nothing changed.
        from tests.test_orchestrated_channel import (
            FakeTranscription,
            ScriptedPanelModel,
            events_of,
            mid_room,
        )
        from app.agents.archetypes import DEFAULT_PANEL
        from app.agents.context import Grounding
        from app.modules.voice.events import RoomTemperature
        from app.modules.voice.orchestrated import OrchestratedChannel
        from app.modules.voice.transcription import Transcription

        channel = OrchestratedChannel(
            panel=DEFAULT_PANEL,
            transcription=FakeTranscription(
                [
                    Transcription(text="Our margin is seventy percent.", final=True),
                    Transcription(text="Off two hundred accounts.", final=True),
                    Transcription(text="CAC pays back in four months.", final=True),
                ]
            ),
            model=ScriptedPanelModel(),
            grounding=Grounding(),
            floor=mid_room(),
        )

        events = await events_of(channel)
        read = [event for event in events if isinstance(event, RoomTemperature)]

        # One, at the open. Nothing after it moved the band, so nothing after it
        # was worth a message.
        assert len(read) == 1
