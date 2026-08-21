import type { PastRoom } from '../api/sessionsApi';
import { panelistName } from '../panel/vocabulary';

/**
 * A past room, said the way somebody would say it.
 *
 * The Library is the first screen about a *history* rather than about one room,
 * and history is where a timestamp stops being data and becomes "yesterday".
 * All of this is presentation, kept out of the component for the reason the
 * debrief keeps its vocabulary out of its sheet: two screens will read these
 * rooms before long — the Library and whatever the progress surface becomes —
 * and a second spelling of "The CFO" is how they come to disagree quietly.
 *
 * `now` is injected on every call rather than read from the clock. Half of what
 * is below is a statement about the present, and a function that consults a
 * global clock can only be tested by freezing one.
 */

const DAY_MS = 24 * 60 * 60 * 1000;

/** Inside this many days, the weekday name still places a room. Past it, it does not. */
const WITHIN_THE_WEEK = 7;

export function whenItRan(startedAt: string, now: Date): string {
  const ran = new Date(startedAt);
  const days = midnightsBetween(ran, now);

  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';

  // "Monday" locates a rehearsal better than "17 August" while it is still
  // inside the week somebody is living in. Past that it is ambiguous — it could
  // be any Monday — and the date becomes the more useful answer.
  if (days < WITHIN_THE_WEEK) {
    return ran.toLocaleDateString('en-GB', { weekday: 'long' });
  }

  return ran.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    // Only when it is not this year. A year on every row is noise on the rows
    // somebody actually reads, to disambiguate the ones they rarely do.
    ...(ran.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }),
  });
}

/**
 * How long the room ran, or null if it never finished.
 *
 * Null rather than zero, and the difference is a claim: a room that failed to
 * provision has a start and no end, and "0:00" says it ran for no time rather
 * than that it never ran. The first is a measurement nobody took.
 */
export function howLongItRan(startedAt: string, settledAt: string | null): string | null {
  if (settledAt === null) return null;

  const seconds = Math.max(
    0,
    Math.round((new Date(settledAt).getTime() - new Date(startedAt).getTime()) / 1000)
  );

  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/**
 * The panel, named as the rest of the product names it.
 *
 * Through `panelistName`, which the debrief and the prep sheet already read.
 */
export function whoWasThere(archetypes: string[]): string {
  const names = archetypes.map(panelistName);

  // A room that failed before seating. Saying nothing leaves a blank where the
  // panel should be, which reads as a rendering fault rather than as a room
  // that never opened.
  if (names.length === 0) return 'Nobody was seated';
  if (names.length === 1) return names[0];

  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

/**
 * Whole days between two moments, counted by midnights rather than by hours.
 *
 * A room at 11pm and a glance at 1am are two hours apart and one *day* apart,
 * and "today" is a claim about the calendar. Counting elapsed hours would call
 * that room "today" until the following evening.
 */
function midnightsBetween(then: Date, now: Date): number {
  const midnight = (at: Date) =>
    new Date(at.getFullYear(), at.getMonth(), at.getDate()).getTime();

  return Math.round((midnight(now) - midnight(then)) / DAY_MS);
}

/**
 * The rung a rehearsal is currently running at, or null if it never ran.
 *
 * **"Run it again" restores the panel and the deck; it has to restore the
 * pressure too.** Until it did, the button handed back a room that pressed
 * differently from the one it named — the rung came from the account, and every
 * debrief moves that, including debriefs of entirely unrelated arguments. A
 * badly handled demo day made somebody's board readout gentler.
 *
 * The server resolves the same thing at room build; this exists so the setup
 * screen can *show* it. A picker still displaying the account's number would
 * state one rung and start another, which is worse than not showing it at all.
 *
 * The newest attempt that actually became a room. A session that failed to
 * provision has no rung — there was no room — so it is skipped rather than
 * inherited as a zero.
 */
export function pressureOf(rooms: PastRoom[], rehearsalId: string): number | null {
  // The rooms arrive newest first, so the first match is the latest attempt.
  const ran = rooms.find(
    (room) => room.rehearsalId === rehearsalId && room.difficultyLevel !== null
  );

  return ran?.difficultyLevel ?? null;
}
