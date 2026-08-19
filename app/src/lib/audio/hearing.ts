import { median } from './level';

/**
 * What the room is picking up, as three states rather than a level.
 *
 * The presenter's question is *is my voice reaching the room* — presence, not
 * loudness — and `InterrogationRoom` carries the argument for why a meter is
 * the wrong answer on a phone lying flat on a desk. This is the classifier
 * behind that indicator.
 *
 * Pure, and over a window rather than a sample, because both of the things
 * that would make it useless are properties of windows: speech has silence in
 * it, and a single buffer is noise.
 */
export type Hearing = 'silent' | 'hearing' | 'faint';

/**
 * Loud enough to be transcribed with confidence.
 *
 * A judgement rather than a measurement, and deliberately generous: the cost
 * of warning somebody who was fine is a sentence they ignore, and the cost of
 * staying quiet while the transcriber guesses is a panel that answers a
 * question the presenter never asked.
 */
export const HEARD_DBFS = -38;

/**
 * Below this there is nothing to warn about, because there is nothing there.
 *
 * A room with the air conditioning on sits somewhere under here. Treating that
 * as a quiet voice would put "we can barely hear you" on screen for a presenter
 * who has simply stopped to think — which the idle timeout, not this, is for.
 */
export const TOO_QUIET_DBFS = -58;

/**
 * How many readings make a window worth judging.
 *
 * At the room's 100ms buffers this is under half a second, which is long enough
 * to contain a syllable and short enough that the indicator still feels live.
 */
const ENOUGH = 4;

export function hearing(recentDbfs: readonly number[]): Hearing {
  if (recentDbfs.length < ENOUGH) {
    return 'silent';
  }

  // The loudest half decides. A median would call a person talking "silent"
  // roughly whenever they were between words — half of any window of real
  // speech is the gaps in it — so the level that matters is the middle of the
  // parts where there was a voice, not the middle of everything.
  const sorted = [...recentDbfs].sort((a, b) => a - b);
  const loudest = sorted.slice(Math.floor(sorted.length / 2));
  const level = median(loudest);

  if (level >= HEARD_DBFS) {
    return 'hearing';
  }

  return level >= TOO_QUIET_DBFS ? 'faint' : 'silent';
}
