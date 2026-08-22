import type { PastRoom } from '../api/sessionsApi';
import { panelistName } from '../panel/vocabulary';
import { clock } from '../replay/clock';

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

const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/** Past this many days, "N days ago" stops being a number anybody holds. */
const IN_MONTHS = 30;

/** And past this, months stop being one too. */
const IN_YEARS = 365;

/**
 * How long ago, as elapsed time rather than as a calendar name.
 *
 * **This replaced weekday names, and the architect asked for it directly:**
 * *"library should work with days ago or years ago or seconds ago basically
 * diff from current time along side date instead of days of the week"*. The
 * weekday was right for the week you are living in and wrong the moment a
 * history got long enough to be worth having — "Monday" could be any Monday,
 * and the fallback to a bare date told you when without telling you how long.
 *
 * **Elapsed under a day, midnights over one.** Two clocks, deliberately: an
 * hour is a duration and a day is a calendar fact. A room at 11pm read at 1am
 * is two hours old, and calling it "0 days ago" would be arithmetic rather than
 * English — so anything that crossed a midnight counts midnights, and anything
 * inside one counts the clock.
 *
 * Months and years are approximated from days, which is the honest precision
 * for a figure nobody checks: "4 months ago" is a placement, not a measurement.
 */
export function howLongAgo(startedAt: string, now: Date): string {
  const ran = new Date(startedAt);
  const elapsed = Math.max(0, now.getTime() - ran.getTime());
  const days = midnightsBetween(ran, now);

  if (days === 0) {
    if (elapsed < MINUTE_MS) return 'Just now';
    if (elapsed < HOUR_MS) return ago(Math.floor(elapsed / MINUTE_MS), 'minute');
    return ago(Math.max(1, Math.floor(elapsed / HOUR_MS)), 'hour');
  }

  if (days < IN_MONTHS) return ago(days, 'day');
  if (days < IN_YEARS) return ago(Math.max(1, Math.round(days / IN_MONTHS)), 'month');

  return ago(Math.max(1, Math.round(days / IN_YEARS)), 'year');
}

/** "3 days ago", and "1 day ago" rather than "1 days ago". */
function ago(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? '' : 's'} ago`;
}

/**
 * The date a room ran, plainly.
 *
 * The year only when it is not this one. A year on every row is noise on the
 * rows somebody actually reads, to disambiguate the ones they rarely do.
 */
export function theDateItRan(startedAt: string, now: Date): string {
  const ran = new Date(startedAt);

  return ran.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    ...(ran.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }),
  });
}

/**
 * How long ago, and when — both, because they answer different questions.
 *
 * "3 days ago" is how you place a room against the meeting you are preparing
 * for. "17 August" is how you find it again, and how you talk about it to
 * anybody else. The old form gave one or the other depending on how old the
 * room was, so the answer you got depended on when you asked.
 *
 * Compact surfaces take `howLongAgo` alone — a dense row has space for the
 * placement and not the date, and the date is the half you can look up.
 */
export function whenItRan(startedAt: string, now: Date): string {
  return `${howLongAgo(startedAt, now)} · ${theDateItRan(startedAt, now)}`;
}

/**
 * How long the room ran, or null if it never finished.
 *
 * Null rather than zero, and the difference is a claim: a room that failed to
 * provision has a start and no end, and "0:00" says it ran for no time rather
 * than that it never ran. The first is a measurement nobody took.
 *
 * Said by `clock`, which the playhead on `RoomPlayback` also uses. A room's
 * length and how far into it you are are the same figure read twice, and this
 * used to spell it itself — which is why an hour-long room read "90:00" here
 * and would have read "1:30:00" three lines below it.
 */
export function howLongItRan(startedAt: string, settledAt: string | null): string | null {
  if (settledAt === null) return null;

  return clock(
    Math.round((new Date(settledAt).getTime() - new Date(startedAt).getTime()) / 1000)
  );
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
