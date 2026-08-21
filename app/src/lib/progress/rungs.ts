import type { RoomHeld } from '../api/progressApi';

/**
 * The one comparison this product is allowed to make.
 *
 * Progress refuses totals, averages, percentages and verdicts, and the reason
 * is always the same one: difficulty escalates (#55), so a count of what got
 * past somebody can rise while they improve. A figure shown without the level
 * it was earned at would tell an improving presenter they are getting worse.
 *
 * **That argument forbids comparing rooms at different rungs. It says nothing
 * against comparing two rooms at the same one.** There the confounder is held
 * constant, and the comparison is a fact rather than an encouragement. The
 * architect asked twice for somebody to be able to tell whether they are doing
 * well — *"user needs to know if they are doing well in general and in
 * presenting a particular thing"* — while also drawing the line that matters:
 * *"we need to be careful to avoid giving user false hope."* Refusing every
 * comparison satisfies the second by abandoning the first, which is caution
 * rather than honesty.
 *
 * So this is the strongest claim the data actually supports, and no stronger.
 * It returns the tallies; it does not subtract them, rank them, or say which
 * way they went. What they add up to stays the presenter's to read.
 *
 * **Scoped to one rehearsal by its caller.** Two rooms at Standard about two
 * different arguments are not a comparison either — the panel differs, the
 * material differs, and the only thing shared is a number. Passing the whole
 * history in here would rebuild the average across incomparable rooms that the
 * screen exists without.
 */

/** Every attempt a rehearsal made at one rung. */
export interface HeldAtOneRung {
  /** The rung all of these ran at. Named for display by the screen. */
  level: number;
  /** Oldest first, because this is read as a sequence. */
  attempts: { held: number; challenged: number }[];
}

/** Below this many attempts at a rung, there is nothing to compare. */
const A_COMPARISON = 2;

/**
 * One rehearsal's rooms, gathered into the rungs it ran at more than once.
 *
 * Rungs ascending, so a presenter who moved up the ladder reads their history
 * in the order they lived it.
 */
export function atTheSameRung(rooms: RoomHeld[]): HeldAtOneRung[] {
  const rungs = new Map<number, RoomHeld[]>();

  for (const room of rooms) {
    // A null rung is a room predating the ladder, and its difficulty is simply
    // unknown. Folding those together as one shared level would compare rooms
    // whose difficulty nobody recorded — the exact mistake the rule exists
    // against, arriving through the back door.
    //
    // A room where nobody was asked anything has no proportion either. Pairing
    // a technical failure with a real attempt would read as somebody collapsing
    // between two afternoons.
    if (room.level === null || room.challenged === 0) continue;

    const run = rungs.get(room.level);
    if (run === undefined) {
      rungs.set(room.level, [room]);
    } else {
      run.push(room);
    }
  }

  return [...rungs.entries()]
    .filter(([, run]) => run.length >= A_COMPARISON)
    .sort(([one], [other]) => one - other)
    .map(([level, run]) => ({
      level,
      // Reversed because the rooms arrive newest first, which is right for a
      // list somebody is scanning and wrong for anything read as a sequence.
      // Reversed here rather than at the screen, so one rule about which way
      // time runs serves the chart and this line both.
      attempts: [...run]
        .reverse()
        .map((room) => ({ held: room.held, challenged: room.challenged })),
    }));
}
