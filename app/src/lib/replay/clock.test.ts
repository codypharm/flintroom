import { clock } from './clock';

/**
 * One spelling of a duration, for two things that show one.
 *
 * The Library says how long a room ran; a playhead says how far into it you
 * are. They are the same figure read twice, and two implementations of
 * `m:ss` is how they come to disagree about the room that ran for an hour.
 */

it('reads as a stopwatch, not as a number of seconds', () => {
  expect(clock(0)).toBe('0:00');
  expect(clock(7)).toBe('0:07');
  expect(clock(67)).toBe('1:07');
  expect(clock(600)).toBe('10:00');
});

it('grows an hours field only once there is an hour', () => {
  // A room is not capped — allowances are monthly, not per room — so a long
  // readout really can pass sixty minutes. "90:00" is a number of minutes
  // wearing a clock's punctuation, and nobody reads it as an hour and a half.
  expect(clock(3599)).toBe('59:59');
  expect(clock(3600)).toBe('1:00:00');
  expect(clock(5407)).toBe('1:30:07');
});

it('pads the minutes only once they are inside an hour', () => {
  // "1:4:07" is not a time. Inside an hour the minutes are the leading figure
  // and lead with a bare digit, the way a stopwatch does.
  expect(clock(247)).toBe('4:07');
  expect(clock(3847)).toBe('1:04:07');
});

it('never reports a position it was not given', () => {
  // A player asks for this before anything has loaded, and `duration` is 0
  // until the file's header is read. A blank there reads as a broken row and
  // a NaN reads as a crash; zero is the truth at that moment.
  expect(clock(-1)).toBe('0:00');
  expect(clock(Number.NaN)).toBe('0:00');
  expect(clock(Number.POSITIVE_INFINITY)).toBe('0:00');
});

it('does not invent a second that has not finished', () => {
  // Position arrives as a float from the audio thread. Rounding up would show
  // the last second of a room before it has been heard, and a player that
  // reads 12:00 of 12:00 while still speaking looks stuck.
  expect(clock(6.99)).toBe('0:06');
});
