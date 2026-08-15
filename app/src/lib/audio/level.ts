/**
 * Signal levels, for deciding whether the room hears itself.
 *
 * The echo spike (task #17) asks one question: with panel audio leaving the
 * speaker and the mic open, does our own voice come back in loudly enough that
 * the provider's VAD calls it a barge-in? `docs/voice-latency.md` records that
 * real `vad_score` values are bimodal — 0.00 or 1.00, nothing between — so
 * there is no gentle degradation to measure. Echo either arrives as speech or
 * it does not.
 *
 * That makes the useful measurement acoustic rather than semantic: how far the
 * captured level rises above the room's own noise floor when playback starts.
 * A working acoustic echo canceller leaves it flat.
 */

/** Level below which everything is reported as silence, in dBFS. */
const FLOOR_DBFS = -120;

/**
 * How far above the noise floor counts as the mic hearing the speaker.
 *
 * A judgement, not a measurement. The provider's own VAD is bimodal and opaque,
 * so this is the bar at which we stop trusting the acoustic path.
 */
export const ECHO_OVER_FLOOR_DB = 6;

/**
 * Absolute level at which playback is audible speech regardless of the floor.
 *
 * Used only when the floor has been gated away (see `isGatedFloor`). Set well
 * below the -26.6 dBFS the stock library measured with no cancellation at all,
 * and well above a genuinely suppressed room.
 */
export const ECHO_ABSOLUTE_DBFS = -45;

/**
 * Root mean square of a normalised (-1..1) buffer.
 *
 * RMS rather than peak because a single sample says nothing about how loud
 * something sounds, and one stray click would otherwise decide the spike.
 */
export function rms(samples: Float32Array): number {
  if (samples.length === 0) {
    return 0;
  }

  let sumOfSquares = 0;
  for (let i = 0; i < samples.length; i += 1) {
    sumOfSquares += samples[i] * samples[i];
  }

  return Math.sqrt(sumOfSquares / samples.length);
}

/**
 * Amplitude to dBFS, with silence floored rather than infinite.
 *
 * A recorder legitimately returns an all-zero buffer — the first callback
 * before the stream warms up does it every time. `log10(0)` is -Infinity, which
 * poisons every later subtraction into NaN and prints a report that says
 * nothing. Flooring keeps the output readable precisely when the thing being
 * measured is the absence of signal.
 */
export function toDbfs(amplitude: number): number {
  if (amplitude <= 0) {
    return FLOOR_DBFS;
  }

  return Math.max(FLOOR_DBFS, 20 * Math.log10(amplitude));
}

/**
 * Middle value of a series, leaving the caller's array untouched.
 *
 * The spike takes one level per recorder callback and reduces the series with
 * this rather than a mean. A single creak or door during the silent phase would
 * pull a mean noise floor up, and an inflated floor makes the echo above it
 * look smaller than it is — failing in the direction that produces a wrong go
 * decision.
 */
export function median(values: number[]): number {
  if (values.length === 0) {
    return 0;
  }

  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);

  return sorted.length % 2 === 0
    ? (sorted[middle - 1] + sorted[middle]) / 2
    : sorted[middle];
}

/**
 * How far above the silent noise floor the mic sits during playback.
 *
 * Positive means echo is leaking in; near zero means it is not. The sign
 * convention is stated in the tests as a direction rather than a magnitude,
 * because inverting it would turn a no-go result into a go decision.
 */
export function echoAboveFloorDb(
  noiseFloorRms: number,
  duringPlaybackRms: number
): number {
  return toDbfs(duringPlaybackRms) - toDbfs(noiseFloorRms);
}

/**
 * Whether the silent phase measured digital silence rather than a real room.
 *
 * Asking Android for `VOICE_COMMUNICATION` enables noise suppression along with
 * echo cancellation, and NS zeroes a quiet room outright — measured on an S24+,
 * where every sample of all 39 silent-phase buffers came back zero. The floor
 * then pins at the clamp and every ratio against it becomes meaningless.
 */
export function isGatedFloor(noiseFloorDbfs: number): boolean {
  return noiseFloorDbfs <= FLOOR_DBFS;
}

/**
 * The spike's verdict: is the mic hearing the speaker?
 *
 * Two rules, because the measurement has two regimes. Against a real noise
 * floor, what matters is how far playback lifts it. Once noise suppression has
 * gated the floor to nothing, that ratio is ~110 dB whether cancellation is
 * perfect or absent, so the playback level has to be judged on its own terms.
 *
 * Getting this wrong in the lenient direction is the expensive failure: it
 * passes an audio path that will make the panel interrupt itself.
 */
export function hasEcho(
  noiseFloorDbfs: number,
  duringPlaybackDbfs: number
): boolean {
  if (isGatedFloor(noiseFloorDbfs)) {
    return duringPlaybackDbfs > ECHO_ABSOLUTE_DBFS;
  }

  return duringPlaybackDbfs - noiseFloorDbfs >= ECHO_OVER_FLOOR_DB;
}

export type Verdict = 'go' | 'no-go' | 'inconclusive';

/**
 * The verdict, including the case where there is nothing to judge.
 *
 * `hasEcho` answers a yes/no question and therefore cannot say "I did not
 * measure anything" — with no buffers, every level defaults to the silence
 * floor, a gated-quiet room looks exactly like a perfectly cancelled one, and
 * the honest answer and the wrong answer are the same value.
 *
 * That is not hypothetical. A run whose input stream was stolen by an audio
 * routing change delivered zero buffers and the screen printed **GO** — the
 * most dangerous output this instrument can produce, because the whole point of
 * it is to be believed.
 */
export function verdict(
  noiseFloorDbfs: number,
  duringPlaybackDbfs: number,
  buffers: { silent: number; playback: number }
): Verdict {
  // Both phases, because the verdict is a comparison between them and half a
  // run is not half an answer.
  if (buffers.silent === 0 || buffers.playback === 0) {
    return 'inconclusive';
  }

  return hasEcho(noiseFloorDbfs, duringPlaybackDbfs) ? 'no-go' : 'go';
}
