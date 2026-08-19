import { median } from './level';

/**
 * What the room is picking up, as three states rather than a level.
 *
 * The presenter's question is *is my voice reaching the room* — presence, not
 * loudness — and `InterrogationRoom` carries the argument for why a meter is
 * the wrong answer on a phone lying flat on a desk. This is the classifier
 * behind that indicator.
 *
 * **Measured against the room's own floor, not against absolute silence.** The
 * first version used a fixed dBFS band for `faint`, and it was wrong in the
 * way that matters: ordinary room tone — air conditioning, a laptop fan, a
 * street outside — sits at roughly -50 dBFS, which was inside the band. So the
 * room told the presenter it could barely hear them, continuously, while they
 * were saying nothing at all. A warning that fires at the noise floor is worse
 * than no warning, because it teaches people to ignore the one that matters.
 *
 * Every room has a different floor. The only honest question is how far above
 * ITS OWN floor the signal has risen, which is the same question
 * `echoAboveFloorDb` asks for the echo spike, for the same reason.
 */
export type Hearing = 'silent' | 'hearing' | 'faint';

/**
 * How far above the room's floor counts as being heard properly.
 *
 * Conversational speech at arm's length runs 15–25 dB over a quiet room's
 * floor. Twelve is comfortably under that and comfortably over the couple of
 * decibels a fan varies by.
 */
export const HEARD_OVER_FLOOR_DB = 12;

/**
 * Where "there is a voice, and it is too quiet" begins.
 *
 * The band between this and `HEARD_OVER_FLOOR_DB` is the only place the warning
 * ever speaks. Deliberately narrow: this is the one state that interrupts, and
 * it has already cried wolf once.
 */
export const FAINT_OVER_FLOOR_DB = 5;

/**
 * Loud enough to be speech whatever the floor says.
 *
 * The floor is estimated from the quiet part of the window, so somebody who
 * talks without pausing for the whole window drags their own floor up and would
 * otherwise measure as a small rise over a loud room. This is the guard against
 * that: past here it is speech, and no arithmetic about floors is going to
 * change it.
 */
export const CLEARLY_SPEECH_DBFS = -30;

/**
 * Below this there is nothing to reason about.
 *
 * A digital-silence window has no floor worth estimating, and dividing a room's
 * behaviour by the difference between two effectively-zero readings is how a
 * classifier becomes a random number generator.
 */
export const NOTHING_DBFS = -70;

/**
 * How long one reading covers, in milliseconds.
 *
 * **Derived, because guessing it is what broke this.** `uplink.FRAME_SAMPLES`
 * is 320 at 16 kHz, so the recorder delivers a buffer every 20ms — and every
 * window here was originally sized in the belief that it delivered one every
 * 100ms. The result was a classifier judging four hundred milliseconds of room
 * fifty times a second, which on a device read as the warning "jerking".
 *
 * Stated here rather than imported so `audio/` does not depend on `voice/`,
 * and asserted against the real frame in `hearing.test.ts`.
 */
export const BUFFER_MS = 20;

/**
 * How many readings make a window worth judging.
 *
 * Half a second — long enough to contain both a syllable and the gaps around
 * it, which is exactly what the floor estimate needs. Below that the quiet
 * quarter is as likely to be the middle of a word as the room.
 */
export const ENOUGH = 25;

/**
 * How much of the recent past the indicator judges.
 *
 * Two seconds, which holds the pauses inside a sentence without lagging so far
 * behind that somebody who has stopped talking is still shown as heard.
 *
 * Lives here rather than in the screen because it is a property of the
 * classifier — the window and the thresholds were tuned against each other,
 * and a caller free to pass a different one can silently make `hearing` mean
 * something else.
 */
export const HEARD_WINDOW = 100;

export function hearing(recentDbfs: readonly number[]): Hearing {
  if (recentDbfs.length < ENOUGH) {
    return 'silent';
  }

  const sorted = [...recentDbfs].sort((a, b) => a - b);

  // The quiet quarter is the room; the loud half is whatever is happening in
  // it. Speech is roughly half gaps, so the quiet end of any window of somebody
  // talking is still the room itself.
  const floor = median(sorted.slice(0, Math.max(1, Math.floor(sorted.length / 4))));
  const level = median(sorted.slice(Math.floor(sorted.length / 2)));

  if (level < NOTHING_DBFS) {
    return 'silent';
  }

  if (level >= CLEARLY_SPEECH_DBFS || level - floor >= HEARD_OVER_FLOOR_DB) {
    return 'hearing';
  }

  return level - floor >= FAINT_OVER_FLOOR_DB ? 'faint' : 'silent';
}


/**
 * How loud the room is right now, from nothing to plainly speaking.
 *
 * Zero to one, measured against the room's own floor for the same reason
 * `hearing` is: a fixed scale would read a quiet office as a whisper and a
 * noisy one as a shout.
 *
 * **This is the amplitude, and handing it to the screen was the architect's
 * call.** The argument against was that a bar tracking volume teaches people to
 * watch how loud they are rather than what they are saying, which is the
 * delivery-metrics product this one exists to refuse. That was raised twice and
 * overruled twice; what is built is what was asked for. Recorded here so the
 * next person to read it knows it was a decision rather than a drift.
 */
export function loudness(recentDbfs: readonly number[]): number {
  if (recentDbfs.length === 0) {
    return 0;
  }

  const sorted = [...recentDbfs].sort((a, b) => a - b);
  const floor = median(sorted.slice(0, Math.max(1, Math.floor(sorted.length / 4))));
  const now = recentDbfs[recentDbfs.length - 1];

  if (now < NOTHING_DBFS) {
    return 0;
  }

  // Clamped to the span the indicator can actually show. Past a full bar there
  // is nothing left to say; below the floor there is nothing to say.
  return Math.max(0, Math.min(1, (now - floor) / FULL_BAR_DB));
}

/** The rise, in dB, that fills the indicator. Roughly a raised speaking voice. */
const FULL_BAR_DB = 22;

/**
 * How many consecutive readings a change must survive before it is shown.
 *
 * **A window length alone cannot fix this.** However long the window, a signal
 * sitting exactly on `FAINT_OVER_FLOOR_DB` crosses it constantly, and the one
 * state this classifier drives is a line of text that interrupts somebody
 * mid-sentence. A warning that appears and disappears is worse than no warning:
 * it teaches people to ignore the one that matters, which is the same failure
 * the absolute-band version already committed once.
 *
 * Forty readings is 0.8s at `BUFFER_MS`. Long enough that nothing flickers,
 * short enough that somebody who has genuinely drifted out of range is told
 * about it while it is still useful to them.
 */
export const STEADY_READINGS = 40;

export interface Steadied {
  /** What the room is currently saying. */
  shown: Hearing;
  /** How many readings in a row have disagreed with it. */
  agreeing: number;
}

/**
 * What to show, given what is shown and what was just read.
 *
 * Symmetric on purpose. A warning that vanishes on one loud buffer flickers
 * exactly as badly as one that appears on one quiet one, so a change out of the
 * warning has to hold for as long as a change into it.
 *
 * Pure and counter-based rather than timed, so the screen holds no clock and a
 * test needs no fake one — and so the hysteresis is measured in the same units
 * as everything else here.
 */
export function steadied(state: Steadied, reading: Hearing): Steadied {
  if (reading === state.shown) {
    return { shown: state.shown, agreeing: 0 };
  }

  const agreeing = state.agreeing + 1;

  return agreeing >= STEADY_READINGS
    ? { shown: reading, agreeing: 0 }
    : { shown: state.shown, agreeing };
}
