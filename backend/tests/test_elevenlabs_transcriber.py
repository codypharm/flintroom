"""Hearing the user, over ElevenLabs Scribe v2 Realtime.

The last vendor in the chain, and the one chosen on arithmetic rather than
preference: ~150ms partials at $0.39/hr against Deepgram's ~300ms at $0.46/hr,
speaking `pcm_16000` natively — byte-for-byte what the relay already carries in
both directions, so nothing between the phone and the transcriber transcodes.
AssemblyAI was ruled out on billing shape rather than quality: it charges for
how long the socket stays open, and a hostile Q&A is full of silence while
somebody works out how to answer. We would have paid for thinking time.

Same split as `test_elevenlabs_adapter.py`, for the same reason. Translation is
a pure function tested exhaustively; the socket is faked, because it is a
network and a paid account, and neither is where the bugs live.
"""

from __future__ import annotations

import base64
import logging
import json
from contextlib import asynccontextmanager
from unittest import mock

import pytest

from app.core.config import Settings
from app.core.errors import ProviderUnavailable
from app.modules.voice.transcribers import build_transcriber
from app.modules.voice.transcription import Transcriber, TranscriptionStream
from app.modules.voice.transcribers.elevenlabs import (
    AUDIO_FORMAT,
    DEFAULT_TRANSCRIPTION_MODEL,
    SAMPLE_RATE,
    SILENCE_THRESHOLD_SECS,
    ElevenLabsTranscriber,
    ElevenLabsTranscriptionStream,
    to_transcription,
)


def test_a_partial_is_the_user_still_talking():
    """The message the whole latency budget is built on.

    Partials are not a nicety here. The selection hop measures ~0.8s, and the
    only reason the room lands inside the ~1.5s threshold is that it runs
    against a partial while the user is still speaking, so the choice of who
    answers has already been made by the time they stop. A transcriber that
    spoke only at the end of an utterance would put the room over budget by
    construction — which is why `Transcription.final` exists at all, and why it
    was weighed above latency when this vendor was picked.
    """
    result = to_transcription({"message_type": "partial_transcript", "text": "our margin is"})

    assert result is not None
    assert result.text == "our margin is"
    assert result.final is False


def test_a_committed_transcript_is_the_user_having_stopped():
    """The only message a panelist is allowed to answer.

    Under `commit_strategy=vad` the engine decides where an utterance ends and
    commits it; this is that decision arriving. Answering anything else means
    answering a sentence the user had not finished — the single most expensive
    mistake this adapter could make, because it burns a metered turn on half a
    thought and makes the room feel like it is talking over you.
    """
    result = to_transcription(
        {"message_type": "committed_transcript", "text": "our margin is sixty-one percent"}
    )

    assert result is not None
    assert result.text == "our margin is sixty-one percent"
    assert result.final is True


@pytest.mark.parametrize(
    "message_type", ["auth_error", "quota_exceeded", "unaccepted_terms", "transcriber_error"]
)
def test_an_unrecoverable_error_ends_the_room_without_naming_the_vendor(message_type):
    """CLAUDE.md: provider failures surface as ProviderUnavailable, unnamed.

    Naming the vendor to a client exposes internal architecture and goes stale
    the moment transcription is swapped — which is the swap this module exists
    to keep cheap. Upstream already knows how to settle and refund a room on
    this exception; what it must not be handed is a vendor's own error string.
    """
    with pytest.raises(ProviderUnavailable) as raised:
        to_transcription({"message_type": message_type, "error": "your key is wrong"})

    assert "eleven" not in str(raised.value).lower()


@pytest.mark.parametrize(
    "message_type",
    ["insufficient_audio_activity", "commit_throttled", "rate_limited", "input_error"],
)
def test_a_survivable_error_never_ends_the_room(message_type):
    """The failure mode that would look exactly like a working product.

    `insufficient_audio_activity` is the dangerous one. Silence is an ordinary
    part of a hostile Q&A — somebody thinking before answering a question about
    their own margins is still in the room — and a transcriber that reports
    quiet must not be able to end a metered session over it. Deciding a room is
    abandoned is the idle timeout's job, on a clock the session owns.

    The others are per-chunk complaints: one rejected chunk, one throttled
    commit. Tearing down a live interrogation over any of them would refund the
    minutes and still lose the user the room they came for.
    """
    assert to_transcription({"message_type": message_type, "error": "quiet"}) is None


# --- The socket ------------------------------------------------------------
#
# Faked, because it is a network and a paid account — `mocking.md` names both as
# boundaries. What stays real is everything we decide: what goes on the wire,
# how the connection is addressed, and what a dropped one turns into.


class FakeSocket:
    """A websocket that replays scripted frames and records what we sent."""

    def __init__(self, incoming: list[str] | None = None) -> None:
        self.incoming = incoming or []
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def __aiter__(self):
        for frame in self.incoming:
            yield frame


async def test_audio_goes_out_base64_encoded_and_uncommitted():
    """Base64 is their wire requirement, applied here and only here.

    The leg from the phone carries raw binary frames; paying the 33% expansion
    on both would be bandwidth spent to satisfy a requirement that exists on
    one of them.

    `commit: false` on every chunk is the load-bearing half. Sending `true`
    would finalise the utterance at that byte, chopping the user off
    mid-sentence and handing the panel a fragment to answer — we have asked the
    engine to find those boundaries with VAD precisely so that this code does
    not have to guess at them.
    """
    socket = FakeSocket()
    pcm = b"\x10\x11\x12\x13"

    await ElevenLabsTranscriptionStream(socket).send_audio(pcm)

    assert json.loads(socket.sent[0]) == {
        "message_type": "input_audio_chunk",
        "audio_base_64": base64.b64encode(pcm).decode(),
        "commit": False,
        "sample_rate": SAMPLE_RATE,
    }


async def test_results_carry_the_utterance_building_up_and_then_settling():
    """Partials are whole utterances, not deltas — and that is load-bearing.

    Their protocol re-sends everything since the last commit, which is what
    `Transcription.text` promises upstream: whoever holds the newest string
    holds the whole sentence. The alternative contract, fragments to be
    accumulated, would put the burden of being correct on every consumer, and
    the selection hop would be reading a partial sentence assembled by us
    rather than by the engine that heard it.
    """
    socket = FakeSocket(
        [
            '{"message_type": "session_started"}',
            '{"message_type": "partial_transcript", "text": "our margin"}',
            '{"message_type": "partial_transcript", "text": "our margin is sixty-one"}',
            '{"message_type": "committed_transcript", "text": "our margin is sixty-one percent"}',
        ]
    )

    heard = [result async for result in ElevenLabsTranscriptionStream(socket).results()]

    assert [(result.text, result.final) for result in heard] == [
        ("our margin", False),
        ("our margin is sixty-one", False),
        ("our margin is sixty-one percent", True),
    ]


async def test_one_utterance_is_answered_once_however_many_times_it_is_declared_final():
    """Insurance against an ambiguity in their documentation, priced in turns.

    `final_transcript` and `committed_transcript` are both documented, and
    which one VAD emits is not stated. `to_transcription` accepts both, because
    recognising only the wrong one would leave a room that hears every word and
    never answers. If it turns out both arrive for one utterance, the panel
    would interrogate the same sentence twice — two model calls, two
    syntheses, two metered turns, and a room that repeats itself at the user.

    So the repeat is dropped here, where there is state to notice it. Compared
    against the previous final rather than against everything ever said: a user
    who answers "no" twice in a row over separate VAD segments meant it twice,
    and the room should hear both.
    """
    socket = FakeSocket(
        [
            '{"message_type": "final_transcript", "text": "we ship in Q3"}',
            '{"message_type": "committed_transcript", "text": "we ship in Q3"}',
            '{"message_type": "partial_transcript", "text": "and"}',
            '{"message_type": "committed_transcript", "text": "and margins hold"}',
        ]
    )

    heard = [result async for result in ElevenLabsTranscriptionStream(socket).results()]

    assert [(result.text, result.final) for result in heard] == [
        ("we ship in Q3", True),
        ("and", False),
        ("and margins hold", True),
    ]


async def test_dialling_asks_the_engine_to_find_the_turn_boundaries():
    """`commit_strategy=vad` is the difference between a product and a demo.

    Manual is their default, and under it *we* would decide where an utterance
    ends — which means writing voice-activity detection, in Python, over a
    network hop, for a hands-free room where the user is not touching the phone
    and cannot tell us they have finished. VAD hands that back to the engine
    that is already listening to the audio.

    The rest of the handshake is the format contract. `pcm_16000` is what the
    phone records and what the panel answers in, so asking for anything else
    would insert a transcode into a latency budget that has no room for one.
    """
    socket = FakeSocket()

    @asynccontextmanager
    async def connects(url, **kwargs):
        connects.url = url
        connects.headers = kwargs.get("additional_headers")
        yield socket

    transcriber = ElevenLabsTranscriber(api_key="secret-key", connect=connects)
    async with transcriber.open():
        pass

    assert f"model_id={DEFAULT_TRANSCRIPTION_MODEL}" in connects.url
    assert f"audio_format={AUDIO_FORMAT}" in connects.url
    assert "commit_strategy=vad" in connects.url
    assert f"vad_silence_threshold_secs={SILENCE_THRESHOLD_SECS}" in connects.url
    assert connects.headers == {"xi-api-key": "secret-key"}


async def test_a_transcriber_that_cannot_be_reached_never_names_the_vendor():
    """A dial failure is a room that never opened, and upstream settles it.

    DNS failure, refused connection, TLS error — identical from the session's
    point of view. What matters is that none of them reach the caller wearing a
    vendor's exception type.
    """

    @asynccontextmanager
    async def refuses(url, **kwargs):
        raise OSError("no route to host")
        yield  # pragma: no cover

    with pytest.raises(ProviderUnavailable):
        async with ElevenLabsTranscriber(api_key="k", connect=refuses).open():
            pass  # pragma: no cover


def test_the_adapter_satisfies_the_seam_it_was_written_for():
    """The `Transcriber` Protocol is structural, so nothing else checks this.

    There is no base class to inherit and no import to get wrong: a rename here
    would leave every test above green and fail only where the adapter is
    handed to `OrchestratedProvider` — at runtime, in a live room. This is the
    assertion that turns that into a test failure.
    """
    assert isinstance(ElevenLabsTranscriber(api_key="k"), Transcriber)
    assert isinstance(ElevenLabsTranscriptionStream(FakeSocket()), TranscriptionStream)


#: The minimum a `Settings` needs to construct at all, matching the convention
#: in `test_claude_extraction.py`. `_env_file=None` keeps a developer's real
#: `.env` out of the assertion.
BASE_ENVIRONMENT = {
    "DATABASE_URL": "postgresql+asyncpg://user:pw@localhost:5432/flintroom",
    "JWT_SECRET": "x" * 48,
    "GOOGLE_CLIENT_ID": "297.apps.googleusercontent.com",
    "APPLE_CLIENT_ID": "com.flintroom.app",
}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **BASE_ENVIRONMENT, **overrides)


async def test_how_long_a_pause_lasts_can_be_changed_without_a_deploy():
    """The one number in the latency budget nothing can measure for us.

    It decides when the engine calls a turn over, so it sits directly inside
    perceived latency — 0.77s of a 2.15s room at the current value, and the
    largest remaining term after composition. Lowering it is the cheapest
    latency left.

    It is also the only term with a floor no measurement can find. Too low and
    the panel talks over somebody drawing breath mid-answer, which is worse than
    a pause: a room that interrupts you cannot be argued with. Synthetic speech
    has no mid-sentence hesitations, so no test and no scripted spike can say
    where that line is — only a person, in a real room, pausing the way people
    actually pause.

    So it is a setting rather than a constant. Judging it means hearing 0.7
    against 0.4 back to back, and a judgement that costs an edit, a rebuild and
    a redeploy per trial is a judgement nobody makes more than once.
    """
    socket = FakeSocket([])

    @asynccontextmanager
    async def connects(url, **kwargs):
        connects.url = url
        yield socket

    # Substituted where the vendor actually is, so this exercises the same path
    # `build_transcriber` hands a running deployment rather than a seam opened
    # for the test.
    with mock.patch("websockets.connect", connects):
        transcriber = build_transcriber(
            _settings(elevenlabs_api_key="k", vad_silence_threshold_secs=0.4)
        )
        async with transcriber.open():
            pass

    assert "vad_silence_threshold_secs=0.4" in connects.url


def test_a_running_deployment_says_which_pause_length_it_is_using(caplog):
    """The value in force must be readable without opening anybody's `.env`.

    It was not, and the cost showed up the first evening it mattered: a real
    session was judged comfortable in the belief that it ran at 0.4, and the
    file said 0.7. The two differ by 0.30s of latency and by whether the panel
    talks over somebody mid-answer — the whole point of the setting — and
    nothing anywhere could have settled which had been heard.

    At construction, so it is stated once per process rather than per room, and
    on the object that resolved it rather than at the call site that passed it.
    A transcriber built with the adapter's own default reports the same way as
    one configured from `.env`, which is what makes the line trustworthy: it
    says what will be dialled, not what somebody intended.
    """
    with caplog.at_level(logging.INFO):
        ElevenLabsTranscriber(api_key="k", silence_threshold_secs=0.55)

    (line,) = [r for r in caplog.records if r.getMessage() == "transcriber_ready"]
    assert line.context["silence_threshold_secs"] == 0.55
    # Never the key. `CLAUDE.md` permits zero secrets in logs, and a startup
    # line is exactly where one gets casually attached to "useful context".
    assert "k" not in str(line.context.values())


def test_a_deployment_without_credentials_gets_no_transcriber_rather_than_a_broken_one():
    """The same shape as `build_speaker`, for the same reason.

    Returning `None` lets the app boot without ElevenLabs credentials, which is
    what every test in this suite and every local run depends on. The
    alternative — constructing a transcriber that holds an empty key — moves
    the failure from boot to the middle of somebody's first metered room.
    """
    assert build_transcriber(_settings(elevenlabs_api_key=None)) is None
    assert isinstance(build_transcriber(_settings(elevenlabs_api_key="k")), Transcriber)
