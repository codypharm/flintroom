"""Read a WAV and print how loud it is, in 100 ms slices.

    uv run python -m scripts.wav_level capture.wav

The measuring end of the echo spike. `docs/echo-cancellation.md` decides go or
no-go on a number this prints, and the phone can only hand over a file — so
without this, that document asks the reader to eyeball a waveform.

Three figures, and the argument needs all three:

- **Per-100 ms RMS** is the one that carries the finding. A residual capture is
  not one level; it is silence where the echo canceller is winning and speech
  where the near end is talking, and only the slices show which is which. The
  proof that Android's suppressor cancels rather than mutes is a *pattern* in
  this column — digital zero during the speaker's pauses while the far end is
  still playing.
- **Peak** catches a microphone that clipped, which invalidates a run.
- **Overall RMS** is comparable between runs, and belongs in the table.

`-120.0 dBFS` means *exactly zero*, not "very quiet": the floor is a printing
convention for log(0). That distinction matters here, because exact zero is the
signature of a residual-echo suppressor gating its output, while genuine
subtraction leaves something behind.

Deliberately stdlib-only. It runs against files pulled off a handset during a
spike, and a measuring instrument that needs its own install is one more thing
to be wrong when the reading is surprising.
"""

from __future__ import annotations

import argparse
import math
import struct
import wave

# Below this, report the floor rather than a number: RMS is exactly zero and the
# logarithm has nowhere to go. Kept as a constant because it appears in the
# document's tables and has to mean the same thing there.
SILENCE_FLOOR_DBFS = -120.0

WINDOW_MS = 100
COLUMNS = 10


def dbfs(amplitude: float) -> float:
    """Amplitude in [0, 1] as dBFS, with digital silence reported as the floor."""
    return 20 * math.log10(amplitude) if amplitude > 0 else SILENCE_FLOOR_DBFS


def samples(raw: bytes, width: int) -> list[float]:
    """Interleaved PCM as floats in [-1, 1].

    Both widths are needed and neither is a choice we make: the wire format in
    `docs/voice-stream-protocol.md` is 16-bit, while the recorder writes its
    capture files as 24-bit. A spike that only read one of them would measure
    whichever was less interesting that day.
    """
    if width == 2:
        return [v / 32767.0 for v in struct.unpack(f"<{len(raw) // 2}h", raw)]

    if width == 3:
        return [
            int.from_bytes(raw[i : i + 3], "little", signed=True) / 8388607.0
            for i in range(0, len(raw), 3)
        ]

    raise SystemExit(f"unhandled sample width: {width * 8}-bit")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="WAV file, 16- or 24-bit PCM")
    args = parser.parse_args()

    with wave.open(args.path, "rb") as handle:
        frames = handle.getnframes()
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        raw = handle.readframes(frames)

    print(
        f"frames={frames} ch={channels} width={width * 8}bit "
        f"rate={rate} dur={frames / rate:.2f}s"
    )

    values = samples(raw, width)
    if not values:
        raise SystemExit("no audio in file")

    window = rate * channels * WINDOW_MS // 1000

    # A trailing partial window is dropped rather than padded: padding it with
    # nothing drags its RMS down and invents a quiet slice at the end of every
    # capture, which is precisely the reading this script exists to judge.
    slices = [
        dbfs(math.sqrt(sum(x * x for x in values[start : start + window]) / window))
        for start in range(0, len(values) - window + 1, window)
    ]

    print("per-100ms dBFS:")
    for i in range(0, len(slices), COLUMNS):
        row = " ".join(f"{db:6.1f}" for db in slices[i : i + COLUMNS])
        print(f"  {i / COLUMNS:5.1f}s {row}")

    peak = dbfs(max(abs(v) for v in values))
    overall = dbfs(math.sqrt(sum(x * x for x in values) / len(values)))
    print(f"peak={peak:.1f} dBFS  overall_rms={overall:.1f} dBFS")


if __name__ == "__main__":
    main()
