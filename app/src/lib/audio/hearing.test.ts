import { HEARD_DBFS, TOO_QUIET_DBFS, hearing } from './hearing';

/**
 * What the floor indicator is allowed to claim.
 *
 * Three states rather than a level, and the reasoning is in
 * `InterrogationRoom`: a bar that moved with amplitude would be the most
 * attention-capturing object on a screen whose premise is that nobody looks at
 * it, and at sixty centimetres and an oblique angle it could not be read as a
 * quantity anyway. What is left is the only question a presenter actually has —
 * is my voice reaching the room.
 */

/** A window of readings all at one level, which is what a steady voice gives. */
function steady(dbfs: number, samples = 20): number[] {
  return Array.from({ length: samples }, () => dbfs);
}

it('says nothing is arriving when the room is quiet', () => {
  expect(hearing(steady(-70))).toBe('silent');
});

it('says the room is hearing you when you are speaking normally', () => {
  expect(hearing(steady(-20))).toBe('hearing');
});

it('warns when there is a voice there but too little of it', () => {
  // The one thing a presence light cannot carry on its own. It would read
  // "hearing you" while the transcriber gets mush, the room would answer a
  // garbled question, and the panel would look stupid for it.
  expect(hearing(steady((HEARD_DBFS + TOO_QUIET_DBFS) / 2))).toBe('faint');
});

it('is not thrown by the gaps between words', () => {
  // Speech is not continuous. Half of any window of a person talking is the
  // silence between syllables, and a classifier reading the latest buffer
  // would flicker between "hearing" and "silent" several times a second — on
  // an indicator sitting in somebody's peripheral vision.
  const talking = [
    ...steady(-18, 6),
    ...steady(-80, 5),
    ...steady(-16, 6),
    ...steady(-75, 3),
  ];

  expect(hearing(talking)).toBe('hearing');
});

it('waits for enough of a window before claiming anything', () => {
  // The room opens and the first buffer arrives 100ms later. Announcing
  // "barely hear you" off one reading, before the presenter has drawn breath,
  // would be the screen's first act and would be wrong.
  expect(hearing([])).toBe('silent');
  expect(hearing(steady(-20, 2))).toBe('silent');
});
