"""Does the shipping transcriber return words when it is sent words?

    uv run python -m scripts.hear_probe

Throwaway instrument for the "I spoke and the panel said I said nothing" bug.
It drives `ElevenLabsTranscriber` — the adapter the room actually uses — with
real speech paced the way the phone paces it, and prints every result verbatim.

The point is to cut the chain in half. If finals come back carrying the words,
the transcriber hears fine and the fault is upstream of it, on the phone or in
the relay. If they come back empty, the fault is here and #77 is the whole bug.
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import time
import wave
from pathlib import Path

from app.modules.voice.transcribers.elevenlabs import ElevenLabsTranscriber
from scripts.envfile import read_env

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
#: What `uplink.ts` sends: 20 ms at the wire rate.
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * BYTES_PER_SAMPLE * FRAME_MS // 1000

LINE = "Our gross margin is sixty two percent and we expect it to reach seventy by the end of next year."


def utterance(text: str) -> bytes:
    """Say something, as raw PCM16 at 16 kHz mono."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "utterance.wav"
        subprocess.run(
            ["say", "-o", str(path), "--data-format=LEI16@16000", text], check=True
        )
        with wave.open(str(path)) as audio:
            return audio.readframes(audio.getnframes())


def silence(seconds: float) -> bytes:
    return b"\x00" * int(SAMPLE_RATE * BYTES_PER_SAMPLE * seconds)


async def main() -> None:
    speech = utterance(LINE)
    print(f"speech: {len(speech) / (SAMPLE_RATE * BYTES_PER_SAMPLE):.2f}s")

    # Silence at both ends, because the engine commits on a silence threshold.
    # Leading silence also gives it a floor to measure the speech against.
    audio = silence(0.5) + speech + silence(2.0)

    transcriber = ElevenLabsTranscriber(api_key=read_env("ELEVENLABS_API_KEY"))

    async with transcriber.open() as stream:

        async def feed() -> None:
            for at in range(0, len(audio), FRAME_BYTES):
                await stream.send_audio(audio[at : at + FRAME_BYTES])
                # Paced, not blasted. Their VAD reasons about time, and a burst
                # measures a condition no phone ever creates.
                await asyncio.sleep(FRAME_MS / 1000)

        feeding = asyncio.create_task(feed())
        started = time.monotonic()

        try:
            async with asyncio.timeout(25):
                async for result in stream.results():
                    kind = "FINAL  " if result.final else "partial"
                    print(f"{time.monotonic() - started:6.2f}s {kind} {result.text!r}")
        except TimeoutError:
            print("-- stopped listening after 25s --")
        finally:
            feeding.cancel()
            await asyncio.gather(feeding, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
