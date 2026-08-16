"""Turning a written line into a particular panelist's voice.

The half of ElevenLabs we still want. Owning the conversation loop replaced their
*Agents* product, not the vendor — distinct per-archetype voices are the reason
`CLAUDE.md` locked this vendor in, and on a hands-free surface where the phone is
face-down, voice is the only signal of who is challenging you.

Nothing here reaches the real endpoint. What a live call would prove is latency
and cost, and those belong to the §4.3 spike against real invoices rather than to
a test suite that has to pass offline and on every commit.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import ProviderUnavailable
from app.modules.voice.speakers import build_speaker
from app.agents.voices import Voice
from app.modules.voice.speakers.elevenlabs import (
    AUDIO_FORMAT,
    ELEVENLABS_VOICES,
    DEFAULT_SPEECH_MODEL,
    ElevenLabsSpeaker,
)

#: The minimum a `Settings` needs to construct at all. `_env_file=None` alongside
#: it is what stops these reading the developer's real .env — a test that passes
#: or fails on whether somebody happens to hold a key is not a test.
BASE_ENVIRONMENT = {
    "DATABASE_URL": "postgresql+asyncpg://user:pw@localhost:5432/flintroom",
    "JWT_SECRET": "x" * 48,
    "GOOGLE_CLIENT_ID": "297.apps.googleusercontent.com",
    "APPLE_CLIENT_ID": "com.flintroom.app",
}

pytestmark = pytest.mark.asyncio


def speaker_over(handler, **kwargs) -> tuple[ElevenLabsSpeaker, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return ElevenLabsSpeaker(api_key="secret", http=http, **kwargs), seen


def audio(*chunks: bytes):
    return lambda request: httpx.Response(200, content=b"".join(chunks))


async def collect(speaker, **kwargs) -> list[bytes]:
    return [chunk async for chunk in speaker.speak(**kwargs)]


async def test_a_line_is_spoken_by_the_voice_it_was_given():
    """The voice is in the path, which is what makes a panel sound like people.

    Also asserts the format: `pcm_16000` is signed 16-bit little-endian at
    16 kHz, which is what the relay carries and what the phone plays. Anything
    else means a transcode in the middle of a latency budget that is already
    over.
    """
    speaker, seen = speaker_over(audio(b"\x01\x02"))

    await collect(speaker, text="Against what basis?", voice=Voice.MEASURED)

    assert f"/v1/text-to-speech/{ELEVENLABS_VOICES[Voice.MEASURED]}/stream" in str(seen[0].url)
    assert f"output_format={AUDIO_FORMAT}" in str(seen[0].url)
    assert seen[0].headers["xi-api-key"] == "secret"


async def test_the_bytes_arrive_whole_and_in_order():
    """PCM is position-dependent: a reordered or dropped frame is a click.

    This is the weaker half of the streaming story and worth naming as such.
    `MockTransport` hands over a complete body, so no test here can prove the
    adapter reads incrementally rather than buffering — what it can prove is that
    nothing is lost or rearranged on the way through.
    """
    speaker, _ = speaker_over(audio(b"\x01\x02", b"\x03\x04"))

    chunks = await collect(speaker, text="Where is that from?", voice=Voice.PRECISE)

    assert b"".join(chunks) == b"\x01\x02\x03\x04"


class CountingStream(httpx.AsyncByteStream):
    """A response body that records how much of itself was ever pulled.

    The only way to tell reading from buffering at this layer. A complete body —
    which `MockTransport` hands over by default — is consumed identically by
    `aiter_bytes()` and `aread()`, so a test written against one cannot see the
    difference that barge-in depends on.
    """

    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks
        self.pulled = 0

    async def __aiter__(self):
        for chunk in self._chunks:
            self.pulled += 1
            yield chunk


async def test_a_panelist_abandoned_mid_sentence_stops_being_synthesised():
    """The property the whole barge-in feature rests on at this layer.

    An interrupted panelist stops because the room stops reading — there is no
    cancel call, and so nothing can be left half-spoken by one. That only holds
    if the adapter pulls incrementally: a version that read the body first would
    synthesise the entire line before its first frame reached a phone, spending
    the whole budget on speech nobody hears, and would still satisfy every other
    assertion in this file.

    So this takes one frame, walks away, and requires that the rest of the
    utterance was never fetched. Written after the buffering mutation survived a
    weaker version of it.
    """
    body = CountingStream(b"\x01\x02", b"\x03\x04", b"\x05\x06")
    speaker, _ = speaker_over(lambda request: httpx.Response(200, stream=body))

    speaking = speaker.speak(text="Against what basis?", voice=Voice.PRECISE)
    await anext(speaking)
    await speaking.aclose()

    assert body.pulled < 3, "the whole line was synthesised before it was needed"


async def test_an_archetype_with_no_voice_yet_still_speaks():
    """The library ships without voices, and a silent panel is worse than a flat one.

    Refusing here would mean no archetype could be heard until every one of them
    had been assigned a voice — so an unassigned panelist falls back to a default
    rather than to silence.
    """
    speaker, seen = speaker_over(audio(b"\x01"), default_voice_id="house_voice")

    await collect(speaker, text="And the margin?", voice=None)

    assert "/v1/text-to-speech/house_voice/stream" in str(seen[0].url)


async def test_the_lowest_latency_model_is_the_default():
    """~75ms against ~280ms, on a budget already over at 1.5s (Open Risk #3).

    Pinned rather than left to the vendor's default, which is neither the fastest
    nor stable across releases — and a silent change to it would show up as the
    room feeling slower with nothing in our diff to explain it.
    """
    speaker, seen = speaker_over(audio(b"\x01"))

    await collect(speaker, text="Say it plainly.", voice=Voice.PRECISE)

    assert seen[0].read().decode().count(DEFAULT_SPEECH_MODEL) == 1


async def test_a_refusal_becomes_a_502_that_does_not_name_the_vendor():
    """CLAUDE.md: a provider failure must never identify the provider.

    It tells whoever is probing what our architecture is, and it goes stale the
    moment the vendor is swapped — which is the swap this seam exists to permit.
    """
    speaker, _ = speaker_over(lambda request: httpx.Response(401, json={}))

    with pytest.raises(ProviderUnavailable) as refused:
        await collect(speaker, text="Anything.", voice=Voice.PRECISE)

    assert "eleven" not in refused.value.message.lower()
    assert "voice" not in refused.value.message.lower()


async def test_an_unreachable_service_is_a_502_and_not_a_crash():
    """A timeout mid-room is a refund, not a traceback.

    Left broad within httpx's own hierarchy rather than enumerated: a transport
    error class we have not met yet should surface as a 502 the finalizer can
    refund against, never as a 500.
    """

    def refuse(request):
        raise httpx.ConnectError("no route to host")

    speaker, _ = speaker_over(refuse)

    with pytest.raises(ProviderUnavailable):
        await collect(speaker, text="Anything.", voice=Voice.PRECISE)


async def test_a_model_that_cannot_perform_a_tag_never_receives_one():
    """Confirmed by ear against the live account: Flash v2.5 reads them aloud.

    It does not perform them and it does not ignore them — a tagged take ran 5.7s
    against 3.6s for the identical words, and the difference is the model saying
    "sighs" and "sceptical" out loud. A panelist who announces their own stage
    directions is not intimidating, and the composer has no instruction *not* to
    emit brackets, so this is reachable by an ordinary model turn rather than by
    misuse.

    Stripped rather than refused. A line arriving with a tag is still a real
    challenge the user is owed, and dropping four words of stage direction is a
    far smaller loss than dropping the question.
    """
    speaker, seen = speaker_over(audio(b"\x01"))

    await collect(
        speaker,
        text="[sighs] Seventy percent. [sceptical] Which one is it?",
        voice=Voice.MEASURED,
    )

    spoken = json.loads(seen[0].read())["text"]
    assert spoken == "Seventy percent. Which one is it?"


async def test_a_model_that_performs_tags_keeps_them():
    """The same guard must not gag a model that can act on them.

    v3 shows the opposite signature — tagged runs *shorter* than plain, not
    longer — so stripping there would throw away the whole reason to pay its
    extra latency.
    """
    speaker, seen = speaker_over(audio(b"\x01"), model="eleven_v3")

    await collect(speaker, text="[laughs] Alright. But prove it.", voice=Voice.WARM)

    assert json.loads(seen[0].read())["text"] == "[laughs] Alright. But prove it."


async def test_stripping_a_tag_does_not_leave_a_hole_in_the_sentence():
    """Whitespace matters to a synthesiser: it is where the pauses come from.

    A naive removal leaves doubled spaces and a leading gap, which reads to the
    model as hesitation the panelist did not intend.
    """
    speaker, seen = speaker_over(audio(b"\x01"))

    await collect(speaker, text="[sighs]  And   the [beat] margin?", voice=Voice.DRY)

    assert json.loads(seen[0].read())["text"] == "And the margin?"


async def test_a_deployment_with_no_key_has_no_voice_rather_than_no_room():
    """One missing credential costs the panel its voice, not the product.

    An `OrchestratedChannel` without a speaker still transcribes, routes,
    composes and captions — so every part of the room can be built and read
    before a synthesis key exists. Refusing to construct would make one optional
    setting a boot failure for a service that has plenty left to do.
    """
    settings = Settings(_env_file=None, **BASE_ENVIRONMENT)

    assert build_speaker(settings, httpx.AsyncClient()) is None


async def test_a_panelist_never_arrives_half_a_sample_out_of_step():
    """PCM16 is two bytes per sample, and HTTP chunks do not respect that.

    Measured against the live vendor: 16 of 103 chunks came back with an odd
    byte count, the very first among them. A consumer reading Int16s from a
    stream that starts one byte late reads the low half of one sample against
    the high half of the next, for the rest of the utterance — which is not a
    glitch or a click but white noise, and it is what the first audible room on
    a phone produced.

    Whole samples out, and the stray byte carried into the next chunk rather
    than dropped. Dropping it would re-align the stream by throwing away half a
    sample sixteen times per line, which trades a permanent fault for an
    intermittent one and is harder to notice.
    """
    body = bytes(range(256))
    speaker, _ = speaker_over(
        lambda request: httpx.Response(
            200, stream=CountingStream(body[:3], body[3:10], body[10:11], body[11:])
        )
    )

    heard = b""
    async for chunk in speaker.speak(text="Where is that from?", voice="measured"):
        assert len(chunk) % 2 == 0, "a consumer must never be handed half a sample"
        heard += chunk

    # Nothing lost but a trailing half-sample, if the vendor ended mid-sample.
    assert heard == body[: len(body) - len(body) % 2]
