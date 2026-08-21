import type { CoachTurn, SparringAttempt } from '../api/debriefApi';

/**
 * The coaching conversation, in the shape the debrief screen draws. #83.
 *
 * The thread and the re-answers were held only in the screen's own `useState`,
 * so backgrounding the debrief — or tapping back and forward — emptied it of
 * every question the presenter had asked and every re-answer they had made,
 * while the ranked findings above redrew perfectly. The conversation was never
 * lost: `session_coach_turns` and `session_sparring_attempts` have held it
 * since #58 and #59. The read simply never carried it, and the screen never
 * asked.
 *
 * Here rather than inline in the route because the grouping is real logic with
 * a real way to be wrong — routes in this app are thin wiring and carry no
 * tests, which is the right convention only as long as nothing with a failure
 * mode lives in one.
 */

/** One turn as the screen draws it: what was heard, what was said back. */
export interface Exchanged {
  heard: string;
  said: string;
  speech: string;
}

/**
 * A coach turn from the wire, as the screen wants it.
 *
 * `text` becomes `said` because the screen has one word for "what the other
 * party said" across the room and the debrief, and two spellings of that is
 * how two surfaces come to disagree about what they are showing.
 */
export function exchanged(turn: CoachTurn): Exchanged {
  return { heard: turn.heard, said: turn.text, speech: turn.speech };
}

/**
 * Re-answers gathered under the question each one was an answer to.
 *
 * Keyed by `weakRank`, which is how #59 anchors sparring and how the screen
 * already looks attempts up. The wire sends them ordered by rank and then by
 * attempt, so appending preserves the order they were made in and nothing here
 * sorts — a list that reshuffled between reads would move a screen that had
 * not changed.
 *
 * Rank is not an index into the ranked list as far as this is concerned: a
 * rank with no attempts is simply absent, and the screen falls back to an
 * empty list for it.
 */
export function byQuestion(
  attempts: readonly SparringAttempt[]
): Record<number, Exchanged[]> {
  return attempts.reduce<Record<number, Exchanged[]>>((gathered, made) => {
    (gathered[made.weakRank] ??= []).push(exchanged(made));
    return gathered;
  }, {});
}
