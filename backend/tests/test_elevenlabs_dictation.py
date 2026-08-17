"""Hearing one recorded turn, without a socket or an account.

The same split every adapter here makes: everything vendor-shaped stops in one
module, and the interpretation is tested exhaustively over a transport that
never leaves the process.

What matters most in this file is the multipart body. A coaching turn is a file
upload rather than a stream, and the failure that would be hardest to notice is
sending the bytes under the wrong field or with the wrong content type — the
call succeeds, the vendor transcribes silence, and the coach answers a turn the
user never said.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.errors import ProviderUnavailable
from app.modules.voice.dictation import Dictation, Heard
from app.modules.voice.dictations.elevenlabs import (
    ElevenLabsDictation,
    MODEL,
)

CLIP = b"RIFF....WAVEfmt not really audio"


def dictation_over(handler) -> ElevenLabsDictation:
    return ElevenLabsDictation(
        api_key="test-key-with-no-production-counterpart",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def replying(payload: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        handler.request = request
        return httpx.Response(200, json=payload)

    return handler


async def test_a_clip_comes_back_as_what_was_said():
    """The tracer, and the only thing the coach actually needs."""
    dictation = dictation_over(
        replying({"text": "Our payback is about four months.", "duration": 3.5})
    )

    heard = await dictation.hear(CLIP, media_type="audio/wav")

    assert heard == Heard(text="Our payback is about four months.", seconds=3.5)


async def test_the_clip_is_sent_as_a_file_under_the_field_the_vendor_reads():
    """The failure this closes is silent and expensive.

    A body with the audio under the wrong field name, or without a content type,
    is still a 200: the vendor transcribes what it received, which is nothing,
    and the coach replies to an empty turn as though the user had said it. The
    user sees a coach that did not listen and no error anywhere.

    Asserted on the bytes on the wire rather than through a helper, because a
    correct multipart builder wired to nothing looks identical from inside.
    """
    handler = replying({"text": "", "duration": 0})
    await dictation_over(handler).hear(CLIP, media_type="audio/wav")

    sent = handler.request.content
    assert b'name="file"' in sent
    assert b"audio/wav" in sent
    assert CLIP in sent
    assert MODEL.encode() in sent


async def test_the_recorded_format_is_the_one_that_is_sent():
    """A phone sends what it records, not what the relay carries.

    The room's PCM16 constant is a property of that socket; this is an upload,
    and iOS and Android do not record the same container by default. An adapter
    that hard-coded one would work on whichever platform was developed against
    and mis-declare on the other — which the vendor may accept and mis-decode.
    """
    handler = replying({"text": "", "duration": 0})
    await dictation_over(handler).hear(CLIP, media_type="audio/mp4")

    assert b"audio/mp4" in handler.request.content


async def test_a_refusal_arrives_as_our_type_rather_than_the_vendors():
    """`ProviderUnavailable`, and it must not name who was asked.

    CLAUDE.md forbids the vendor in a client-facing error: it exposes internal
    architecture to whoever is probing, and goes stale the moment the provider is
    swapped — which is what the seam above exists to permit.
    """
    dictation = dictation_over(lambda request: httpx.Response(429, json={}))

    with pytest.raises(ProviderUnavailable) as refused:
        await dictation.hear(CLIP, media_type="audio/wav")

    assert "elevenlabs" not in str(refused.value.context).lower()


async def test_a_clip_with_no_speech_in_it_is_an_answer_rather_than_a_failure():
    """Somebody tapped record and said nothing, or the mic was muted.

    An empty string is the truthful result and the caller decides what to do with
    it. Raising here would turn a silent room into a 502 and tell the user the
    service is down, when what happened is that it heard them perfectly.
    """
    dictation = dictation_over(replying({"text": "   ", "duration": 1.2}))

    heard = await dictation.hear(CLIP, media_type="audio/wav")

    assert heard.text == ""
    assert heard.seconds == 1.2


async def test_the_adapter_satisfies_the_seam_it_is_plugged_into():
    """A guard, and the reason `Dictation` is runtime-checkable.

    There is no type checker in the suite, so renaming `hear` would stay green
    in every test above and fail only when somebody spoke to the coach.
    """
    assert isinstance(dictation_over(replying({"text": ""})), Dictation)
