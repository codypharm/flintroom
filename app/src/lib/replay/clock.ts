/**
 * A duration, said the way a clock says it.
 *
 * Two things in this app show one: the Library says how long a room ran, and a
 * playhead says how far into it you are. They are the same figure read twice,
 * which is exactly the case `lib/library/rooms.ts` argues for keeping in one
 * place — a second spelling is how two screens come to disagree quietly about
 * the room that ran for an hour.
 *
 * Seconds in, because that is what both callers hold: the audio thread reports
 * a float position, and a room's length is the difference between two stamps.
 */

const A_MINUTE = 60;
const AN_HOUR = 60 * A_MINUTE;

export function clock(seconds: number): string {
  // A player asks for this before anything has loaded, when `duration` is 0 and
  // position is whatever the native side last said. Neither a blank nor a NaN
  // is a time; zero is what is true at that moment.
  if (!Number.isFinite(seconds) || seconds <= 0) return '0:00';

  // Floored, never rounded. Position arrives as a float, and rounding up would
  // show the last second of a room before it has been heard — a player reading
  // 12:00 of 12:00 while still speaking looks stuck rather than nearly done.
  const whole = Math.floor(seconds);
  const hours = Math.floor(whole / AN_HOUR);
  const minutes = Math.floor((whole % AN_HOUR) / A_MINUTE);
  const rest = whole % A_MINUTE;

  // Minutes lead with a bare digit under an hour and are padded above it. A
  // stopwatch says "4:07"; a clock says "1:04:07", and "1:4:07" is neither.
  if (hours === 0) return `${minutes}:${pad(rest)}`;

  return `${hours}:${pad(minutes)}:${pad(rest)}`;
}

function pad(figure: number): string {
  return String(figure).padStart(2, '0');
}
