"""Talk to a real panel, and time how long it takes to answer back.

    uv run python -m scripts.voice_spike                # 3 turns, header auth
    uv run python -m scripts.voice_spike --turns 1      # cheapest useful run
    uv run python -m scripts.voice_spike --signed-url   # force the other auth

This is the measurement `CLAUDE.md` asks for before the voice layer is trusted:
Open Risk #3 puts the illusion's threshold at ~1.5s, and every latency claim in
the repo so far is an assumption. It answers four open questions in one
connection, because they all need the same expensive thing — real audio through
a real provider:

1. **Latency.** Time from the user finishing a sentence to the first byte of the
   panel's reply. Reported per turn, against the 1.5s threshold.
2. **Handshake auth.** Whether `xi-api-key` is accepted on the WebSocket
   handshake, or whether a signed URL is required. `ElevenLabsProvider.open`
   carries this as an explicit UNVERIFIED note.
3. **VAD calibration.** The distribution of real `vad_score` values while
   someone is speaking and while they are not. `SPEECH_THRESHOLD` is currently
   0.5 by guess, and it decides when a thinking user is thrown out for silence.
4. **Cost.** Wall seconds of connection, which is the unit the provider bills.

It drives the **shipping** adapter — `ElevenLabsProvider`, `to_event`, the
audio-format guard, the pong — rather than a second implementation written to
agree with it. A spike that dials the socket itself measures the spike.

No tests. It is an instrument, not a feature: what it asserts about is the
provider's behaviour on a given afternoon, which is not a thing a test suite can
hold still. The code it exercises is tested; this reports on reality.

macOS only, for the speech: `say` emits LEI16@16000 mono, which is our wire
format exactly, so the utterance reaches the provider without a transcode in the
way of the number we came to measure.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import websockets

from app.core.errors import ProviderUnavailable
from app.modules.voice.events import AgentAudio, ChannelReady
from app.modules.voice.providers.elevenlabs import (
    AUDIO_FORMAT,
    SPEECH_THRESHOLD,
    ElevenLabsProvider,
)
from scripts.envfile import read_env

#: Open Risk #3. Above this the room stops feeling like a room.
LATENCY_BUDGET = 1.5

AGENTS_API = "https://api.elevenlabs.io/v1/convai/agents"

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2

#: What the phone will do: small chunks, paced to real time. Sending five
#: seconds of audio in one burst would measure a condition no user creates, and
#: would likely read as faster than the truth — their endpointing has heard the
#: whole sentence before the speaker would have finished it.
CHUNK_MS = 100

#: Long enough that a panelist pausing mid-sentence does not read as the end of
#: its turn, short enough not to spend free-tier minutes on silence.
QUIET_GAP = 1.5

#: A turn that has not started inside this is not a latency measurement, it is
#: an outage — and waiting longer only spends more of the account.
TURN_TIMEOUT = 20.0

#: Deliberately the kind of thing said in the room: a claim with a number in it,
#: which is what the panel is built to attack. Generic small talk would measure
#: the model's fastest path rather than its working one.
UTTERANCES = [
    "We grew revenue two hundred percent last year and our margin held at sixty two percent.",
    "Our churn is under two percent monthly, which is best in class for this segment.",
    "We only need eighteen months of runway to reach profitability at current burn.",
]


def utterance(text: str, *, voice: str | None) -> bytes:
    """Say something, as raw PCM16 at 16 kHz mono."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "utterance.wav"
        command = ["say", "-o", str(path), "--data-format=LEI16@16000"]
        if voice:
            command += ["-v", voice]
        subprocess.run([*command, text], check=True)

        with wave.open(str(path)) as audio:
            if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) != (
                1,
                SAMPLE_RATE,
                BYTES_PER_SAMPLE,
            ):
                raise SystemExit("`say` produced audio in an unexpected format")
            return audio.readframes(audio.getnframes())


class Observations:
    """Raw frames, kept beside the normalized events.

    `to_event` collapses `vad_score` to spoke-or-not on purpose — upstream has
    no use for the number. Calibrating the threshold needs exactly the number
    that gets thrown away, so it is read here from the wire instead of widening
    the event to carry a field only a script would ever look at.
    """

    def __init__(self) -> None:
        self.vad: list[tuple[float, float]] = []
        self.types: dict[str, int] = {}
        #: When they committed to a finished user turn. Splits a latency number
        #: into the part we can buy back by tuning the agent's turn timeout and
        #: the part that is the model thinking — different problems with
        #: different fixes, indistinguishable in the total.
        self.transcripts: list[float] = []
        self.audio_bytes_in = 0
        self.audio_bytes_out = 0
        self.started = time.monotonic()

    def saw(self, message: dict[str, Any]) -> None:
        kind = str(message.get("type"))
        self.types[kind] = self.types.get(kind, 0) + 1
        if kind == "vad_score":
            score = message["vad_score_event"]["vad_score"]
            self.vad.append((time.monotonic() - self.started, float(score)))
        elif kind == "audio":
            self.audio_bytes_in += len(message["audio_event"]["audio_base_64"])
        elif kind == "user_transcript":
            # The text itself is deliberately not kept. CLAUDE.md forbids
            # transcripts in logs, and a spike's stdout is a terminal
            # somebody will paste somewhere.
            self.transcripts.append(time.monotonic())

    def endpointed_at(self, *, after: float, before: float) -> float | None:
        """When the user's turn was declared over, if that happened in this turn."""
        within = [at for at in self.transcripts if after <= at <= before]
        return within[-1] if within else None


class TeeSocket:
    """The provider's socket, with a copy of everything taken on the way past."""

    def __init__(self, socket: Any, observations: Observations) -> None:
        self._socket = socket
        self._observations = observations

    async def send(self, frame: str) -> None:
        self._observations.audio_bytes_out += len(frame)
        await self._socket.send(frame)

    async def __aiter__(self) -> AsyncIterator[str]:  # pragma: no cover - transport
        async for frame in self._socket:
            try:
                self._observations.saw(json.loads(frame))
            except (ValueError, KeyError, TypeError):
                pass  # Observation only. Never break the room to take a reading.
            yield frame


def _tee(observations: Observations, *, signed_url: str | None) -> Any:
    """A `connect` for the provider that records, and optionally re-dials.

    Both variations live here rather than in the provider because neither is a
    thing production should learn how to do. The signed-URL path exists to
    answer whether the header path works — if the header wins, production never
    needs the other, and if it loses, that becomes a deliberate change to the
    adapter rather than a fallback nobody chose.
    """

    @asynccontextmanager
    async def connect(url: str, **kwargs: Any) -> AsyncIterator[TeeSocket]:
        if signed_url:
            # Their signed URL carries the authorization in the query string, so
            # the header is not merely unnecessary here — sending both is how
            # you learn nothing about which one was accepted.
            url, kwargs = signed_url, {}
        async with websockets.connect(url, **kwargs) as socket:
            yield TeeSocket(socket, observations)

    return connect


def fetch_signed_url(*, api_key: str, agent_id: str) -> str:
    response = httpx.get(
        "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
        params={"agent_id": agent_id},
        headers={"xi-api-key": api_key},
        timeout=20.0,
    )
    response.raise_for_status()
    return response.json()["signed_url"]


async def consume(channel: Any, queue: asyncio.Queue) -> None:
    """Drain the channel into a queue, forever, until it ends.

    A queue rather than reading the generator directly at each waiting point,
    because every read here has a timeout and cancelling `__anext__` on an
    async generator leaves it unusable for the next turn — the measurement
    would break exactly when the provider got slow, which is the case it exists
    to observe.
    """
    try:
        async for event in channel.events():
            await queue.put((time.monotonic(), event))
    except ProviderUnavailable as exc:
        await queue.put((time.monotonic(), exc))
    finally:
        await queue.put((time.monotonic(), None))


async def next_event(queue: asyncio.Queue, *, timeout: float) -> tuple[float, Any] | None:
    try:
        return await asyncio.wait_for(queue.get(), timeout=timeout)
    except TimeoutError:
        return None


async def quiet(queue: asyncio.Queue, *, gap: float = QUIET_GAP, limit: float = 30.0) -> None:
    """Wait until the panel stops talking, without ending the room to do it.

    Only agent audio counts as noise. Pings and VAD scores arrive throughout —
    including while nobody is saying anything, now that the microphone streams
    silence — so treating any event as speech would mean the panel never
    appeared to stop.
    """
    deadline = time.monotonic() + limit
    spoke_at = time.monotonic()
    while time.monotonic() < deadline:
        item = await next_event(queue, timeout=0.2)
        if item is None:
            if time.monotonic() - spoke_at >= gap:
                return
            continue
        _, event = item
        if event is None or isinstance(event, ProviderUnavailable):
            raise SystemExit("the channel closed while waiting for quiet")
        if isinstance(event, AgentAudio):
            spoke_at = time.monotonic()


class Microphone:
    """Streams continuously, the way a phone on a desk does.

    The reason this is not a plain `send the utterance` loop: their endpointing
    decides a turn has ended by *hearing* silence. A client that simply stops
    sending frames has not gone quiet, it has gone away — the first run of this
    spike waited twenty seconds for a reply to a sentence the provider did not
    yet believe was finished.

    Which makes this a finding about the Expo client, not about the script. The
    phone must keep the uplink flowing between sentences; an optimisation that
    suppresses silent frames to save bandwidth would break turn-taking, and
    would do it in a way that looks like model latency.
    """

    CHUNK = SAMPLE_RATE * BYTES_PER_SAMPLE * CHUNK_MS // 1000

    def __init__(self, channel: Any) -> None:
        self._channel = channel
        self._pending = bytearray()
        self._drained = asyncio.Event()
        self._drained.set()

    async def run(self) -> None:
        silence = bytes(self.CHUNK)
        while True:
            started = time.monotonic()
            if self._pending:
                frame = bytes(self._pending[: self.CHUNK])
                del self._pending[: self.CHUNK]
                last = not self._pending
            else:
                frame, last = silence, False
            await self._channel.send_audio(frame)
            if last:
                self._drained.set()
            await asyncio.sleep(max(0.0, CHUNK_MS / 1000 - (time.monotonic() - started)))

    async def say(self, pcm: bytes) -> float:
        """Queue an utterance; return the moment its last frame left."""
        self._drained.clear()
        self._pending.extend(pcm)
        await self._drained.wait()
        return time.monotonic()


async def reply_latency(queue: asyncio.Queue, *, spoken_at: float) -> float | None:
    """Seconds from the end of the sentence to the first byte of the answer.

    A negative result is possible and is not a fast reply — it is the panel
    talking over someone who had not finished. Reported as an interruption
    rather than folded into the median, because averaging it in makes being
    interrupted look like good latency, which is the one conclusion this script
    must never support.
    """
    deadline = spoken_at + TURN_TIMEOUT
    while (item := await next_event(queue, timeout=max(0.0, deadline - time.monotonic()))) is not None:
        at, event = item
        if isinstance(event, AgentAudio):
            return at - spoken_at
        if event is None or isinstance(event, ProviderUnavailable):
            return None
    return None


@dataclass
class Measurement:
    """One connection's worth of numbers."""

    latencies: list[float]
    endpointing: list[float]
    observations: Observations
    connected_for: float
    ready_in: float | None = None
    #: Turns where the panel began answering before the speaker had finished.
    interruptions: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.latencies)

    def median(self) -> float:
        return statistics.median(self.latencies) if self.latencies else float("nan")

    def median_endpointing(self) -> float:
        return statistics.median(self.endpointing) if self.endpointing else float("nan")


def agent_config(*, api_key: str, agent_id: str) -> dict[str, Any]:
    response = httpx.get(
        f"{AGENTS_API}/{agent_id}", headers={"xi-api-key": api_key}, timeout=20.0
    )
    response.raise_for_status()
    return response.json()["conversation_config"]


def patch_agent(*, api_key: str, agent_id: str, conversation_config: dict[str, Any]) -> None:
    response = httpx.patch(
        f"{AGENTS_API}/{agent_id}",
        headers={"xi-api-key": api_key},
        json={"conversation_config": conversation_config},
        timeout=20.0,
    )
    response.raise_for_status()


async def measure(
    *,
    api_key: str,
    agent_id: str,
    utterances: list[bytes],
    signed: str | None,
    verbose: bool = True,
) -> Measurement:
    observations = Observations()
    provider = ElevenLabsProvider(
        api_key=api_key, agent_id=agent_id, connect=_tee(observations, signed_url=signed)
    )

    latencies: list[float] = []
    endpointing: list[float] = []
    interruptions = 0
    ready_in: float | None = None
    dialled = time.monotonic()
    connected_for = 0.0

    def say(line: str) -> None:
        if verbose:
            print(line)

    try:
        async with provider.open() as channel:
            queue: asyncio.Queue = asyncio.Queue()
            reader = asyncio.create_task(consume(channel, queue))
            microphone = Microphone(channel)
            mic = asyncio.create_task(microphone.run())
            try:
                item = await next_event(queue, timeout=TURN_TIMEOUT)
                if item is None or not isinstance(item[1], ChannelReady):
                    say(f"no channel_ready — got {item[1] if item else 'nothing'}")
                    return Measurement([], [], observations, time.monotonic() - dialled)
                ready_in = item[0] - dialled
                say(f"channel ready in {ready_in:.2f}s (agent spin-up)")

                # The agent opens with its first message. That is a greeting, not
                # an answer to anything, so it is waited out rather than timed.
                await quiet(queue)

                for index, pcm in enumerate(utterances, start=1):
                    spoken_at = await microphone.say(pcm)
                    latency = await reply_latency(queue, spoken_at=spoken_at)
                    if latency is None:
                        say(f"turn {index}: no reply within {TURN_TIMEOUT:.0f}s")
                        break
                    if latency < 0:
                        interruptions += 1
                        say(f"turn {index}: INTERRUPTED — the panel started "
                            f"{-latency:.2f}s before the sentence ended")
                        await quiet(queue)
                        continue
                    latencies.append(latency)
                    verdict = "ok" if latency <= LATENCY_BUDGET else "OVER BUDGET"
                    split = ""
                    heard = observations.endpointed_at(
                        after=spoken_at, before=spoken_at + latency
                    )
                    if heard is not None:
                        endpointing.append(heard - spoken_at)
                        split = (f"  (endpointing {heard - spoken_at:.2f}s + "
                                 f"think/speak {spoken_at + latency - heard:.2f}s)")
                    say(f"turn {index}: {latency:.2f}s  {verdict}{split}")
                    await quiet(queue)
            finally:
                mic.cancel()
                reader.cancel()
                await asyncio.gather(mic, reader, return_exceptions=True)
                connected_for = time.monotonic() - dialled
    except ProviderUnavailable as exc:
        connected_for = connected_for or time.monotonic() - dialled
        say(f"\nprovider unavailable: {exc.context.get('reason')}")
        if not signed:
            say("if this was the dial, re-run with --signed-url to see whether "
                "the handshake wants one.")
        return Measurement([], [], observations, connected_for)

    return Measurement(
        latencies, endpointing, observations, connected_for, ready_in, interruptions
    )


def report(measurement: Measurement) -> None:
    observations = measurement.observations
    print()
    if measurement.latencies:
        print(f"latency   : median {measurement.median():.2f}s, "
              f"worst {max(measurement.latencies):.2f}s, budget {LATENCY_BUDGET}s")
        over = [round(value, 2) for value in measurement.latencies if value > LATENCY_BUDGET]
        print(f"            {len(over)} of {len(measurement.latencies)} over budget"
              + (f" — {over}" if over else ""))

    if observations.vad:
        scores = sorted(score for _, score in observations.vad)
        above = sum(1 for score in scores if score >= SPEECH_THRESHOLD)
        print(f"vad       : {len(scores)} samples, "
              f"min {scores[0]:.2f}, median {statistics.median(scores):.2f}, "
              f"max {scores[-1]:.2f}")
        print(f"            {above} ({above / len(scores):.0%}) at or above "
              f"SPEECH_THRESHOLD={SPEECH_THRESHOLD} — the idle clock resets on these")

    print(f"events    : {observations.types}")
    print(f"connected : {measurement.connected_for:.1f}s — what the provider bills, "
          f"and what the meter would have charged")
    print(f"bytes     : {observations.audio_bytes_out / 1024:.0f} KiB up, "
          f"{observations.audio_bytes_in / 1024:.0f} KiB down (base64, provider leg)")


#: The setting suspected of owning the gap between the end of a sentence and the
#: provider accepting that it ended. Everything else is held still, so a
#: difference between rows is attributable to this one.
#:
#: `asr.quality` was in here too, on the theory that transcription was part of
#: the delay. It is not a knob: the API accepts `high` and rejects everything
#: else, so there is no cheaper transcription to trade accuracy for.
SWEEP = [
    {"turn": {"turn_eagerness": eagerness}} for eagerness in ("normal", "eager")
]


async def sweep(*, api_key: str, agent_id: str, utterances: list[bytes]) -> int:
    """Run the same sentences under each candidate configuration.

    Restores whatever was there first, on every path out — this edits a live
    agent, and leaving it configured for whichever row happened to run last is
    a change nobody chose.
    """
    before = agent_config(api_key=api_key, agent_id=agent_id)
    original = {"turn": {"turn_eagerness": before["turn"]["turn_eagerness"]}}
    print(f"restoring afterwards to: {original}\n")

    rows: list[tuple[str, Measurement]] = []
    try:
        for settings in SWEEP:
            label = f"eagerness={settings['turn']['turn_eagerness']:<6}"
            patch_agent(api_key=api_key, agent_id=agent_id, conversation_config=settings)
            # Their config propagates to the conversation service asynchronously;
            # dialling immediately can open a room still running the old row and
            # silently attribute its numbers to this one.
            await asyncio.sleep(3)
            result = await measure(
                api_key=api_key, agent_id=agent_id,
                utterances=utterances, signed=None, verbose=False,
            )
            rows.append((label, result))
            cut = f"  interrupted {result.interruptions}" if result.interruptions else ""
            print(f"{label}  →  " + (
                f"median {result.median():.2f}s  "
                f"(endpointing {result.median_endpointing():.2f}s)  "
                f"turns {[round(v, 2) for v in result.latencies]}{cut}"
                if result.ok else f"no measurement{cut}"
            ))
    finally:
        patch_agent(api_key=api_key, agent_id=agent_id, conversation_config=original)
        print(f"\nrestored: {original}")

    best = min((row for row in rows if row[1].ok), key=lambda row: row[1].median(), default=None)
    if best is not None:
        print(f"\nfastest : {best[0]} at median {best[1].median():.2f}s")
    spent = sum(row[1].connected_for for row in rows)
    print(f"spent   : {spent:.0f}s of connection across {len(rows)} runs")
    return 0


async def run(args: argparse.Namespace) -> int:
    api_key = read_env("ELEVENLABS_API_KEY")
    agent_id = read_env("ELEVENLABS_AGENT_ID")
    utterances = [utterance(text, voice=args.voice) for text in UTTERANCES[: args.turns]]
    speech = sum(len(pcm) for pcm in utterances) / (SAMPLE_RATE * BYTES_PER_SAMPLE)
    print(f"utterances: {len(utterances)}, {speech:.1f}s of speech per run\n")

    if args.sweep:
        return await sweep(api_key=api_key, agent_id=agent_id, utterances=utterances)

    signed = fetch_signed_url(api_key=api_key, agent_id=agent_id) if args.signed_url else None
    print(f"auth      : {'signed url' if signed else 'xi-api-key header'}")
    print(f"format    : {AUDIO_FORMAT}\n")

    result = await measure(
        api_key=api_key, agent_id=agent_id, utterances=utterances, signed=signed
    )
    report(result)
    return 0 if result.ok and result.median() <= LATENCY_BUDGET else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=len(UTTERANCES),
                        help="how many sentences to say (each costs free-tier minutes)")
    parser.add_argument("--signed-url", action="store_true",
                        help="authenticate with a signed URL instead of the header")
    parser.add_argument("--sweep", action="store_true",
                        help="compare turn-detection settings; restores the agent afterwards")
    parser.add_argument("--voice", default=None, help="a `say` voice name")
    args = parser.parse_args()
    args.turns = max(1, min(args.turns, len(UTTERANCES)))
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
