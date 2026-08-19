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
 * How many readings make a window worth judging.
 *
 * At the room's 100ms buffers, twenty is two seconds — long enough to contain
 * both a syllable and the gaps around it, which is exactly what the floor
 * estimate needs.
 */
const ENOUGH = 8;

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
