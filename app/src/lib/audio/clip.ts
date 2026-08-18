import { toWav } from './wav';

/**
 * One spoken turn, gathered from the recorder and handed over as a file.
 *
 * The recorder delivers a buffer every few tens of milliseconds; a coaching
 * turn is seconds long and leaves as a single upload. This holds the middle,
 * and it is deliberately the only place that does — the route above it owns the
 * microphone and the request, and neither needs to know how samples are joined.
 */

/**
 * How long one go can be.
 *
 * Under the server's 10 MB ceiling on purpose. Filling to exactly that trades a
 * sentence this app can say for a 413 that arrives after the bytes have already
 * been sent, and the recovery is identical either way: say it in a shorter go.
 *
 * The case this exists for is not a long answer. It is tapping Talk and putting
 * the phone down — held twice over, as floats and again as PCM, an hour of
 * audio is hundreds of megabytes and the app is killed. From the user's side
 * the debrief simply disappeared.
 */
export const CLIP_CEILING_SECONDS = 300;

export interface Clip {
  /** Take one buffer from the recorder, at whatever rate it arrived. */
  push(samples: Float32Array, sampleRate: number): void;
  /** Whole seconds captured, counted from samples rather than a clock. */
  seconds(): number;
  /** True once no more will be accepted. The caller should stop and send. */
  full(): boolean;
  /** One WAV. Valid with nothing in it — the server names that case. */
  finish(): Blob;
}

export function collectClip(): Clip {
  const taken: Float32Array[] = [];
  let total = 0;
  // Recorded from the first buffer rather than requested, because the rate is a
  // property of what arrived. The recorder is asked for 16 kHz and Android
  // hands back whatever it wanted — #18 exists for exactly this.
  let rate = 16_000;
  let ceiling = CLIP_CEILING_SECONDS * rate;

  return {
    push(samples, sampleRate) {
      if (taken.length === 0) {
        rate = sampleRate;
        ceiling = CLIP_CEILING_SECONDS * rate;
      }

      // Refused whole rather than trimmed to fit. A part-buffer would end the
      // clip mid-syllable at a boundary nobody chose, and the ceiling is
      // already generous enough that the last tenth of a second is not the
      // difference between an answer and a fragment.
      if (total + samples.length > ceiling) return;

      // Copied. The recorder reuses its buffer between callbacks, so keeping the
      // reference would leave every frame in the clip holding whatever was
      // recorded last — silence, or the same tenth of a second repeated.
      taken.push(Float32Array.from(samples));
      total += samples.length;
    },

    seconds: () => Math.floor(total / rate),

    full: () => total >= ceiling,

    finish() {
      const joined = new Float32Array(total);
      let at = 0;
      for (const part of taken) {
        joined.set(part, at);
        at += part.length;
      }

      return new Blob([toWav(joined, rate)], { type: 'audio/wav' });
    },
  };
}
