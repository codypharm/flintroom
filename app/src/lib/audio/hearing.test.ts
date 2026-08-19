import {
  BUFFER_MS,
  CLEARLY_SPEECH_DBFS,
  ENOUGH,
  HEARD_WINDOW,
  STEADY_READINGS,
  hearing,
  loudness,
  steadied,
  type Steadied,
} from './hearing';

/**
 * What the floor indicator is allowed to claim.
 *
 * These exist mostly because of one bug found on a device: the room told the
 * architect it could barely hear them, continuously, while they were saying
 * nothing. The first version judged an absolute dBFS band, and ordinary room
 * tone lives inside it. Every case below is really the same case — the room's
 * own noise is not a quiet voice.
 */

/** A window of readings all at one level.
 *
 * A *full* window by default. The recorder delivers a buffer every 20ms and the
 * screen keeps `HEARD_WINDOW` of them, so anything shorter is a room that has
 * only just opened — which `hearing` deliberately refuses to judge. */
function steady(dbfs: number, samples = HEARD_WINDOW): number[] {
  return Array.from({ length: samples }, () => dbfs);
}

/** A quiet room with a voice in it: gaps at the floor, syllables above it. */
function speech(floor: number, over: number, samples = HEARD_WINDOW): number[] {
  return Array.from({ length: samples }, (_, index) =>
    index % 3 === 0 ? floor : floor + over
  );
}

it('treats a quiet room as silence, not as somebody being too quiet', () => {
  // THE BUG. Air conditioning, a laptop fan and a street outside all land near
  // -50 dBFS, which the first version called "faint" — so the warning fired at
  // the noise floor, forever, while nobody was speaking. A warning that fires
  // at the floor is worse than no warning: it teaches people to ignore the one
  // that matters.
  expect(hearing(steady(-50))).toBe('silent');
  expect(hearing(steady(-45))).toBe('silent');
  expect(hearing(steady(-58))).toBe('silent');
});

it('says nothing is arriving when the room is properly quiet', () => {
  expect(hearing(steady(-75))).toBe('silent');
});

it('hears somebody speaking over a quiet room', () => {
  expect(hearing(speech(-52, 20))).toBe('hearing');
});

it('hears somebody speaking over a loud room', () => {
  // The same voice in a noisier room. Judged on the rise, so a café does not
  // become "we cannot hear you" for somebody who is perfectly audible.
  expect(hearing(speech(-38, 20))).toBe('hearing');
});

it('hears somebody who never pauses long enough to reveal the floor', () => {
  // Continuous speech drags its own floor estimate up, so the rise collapses.
  // Past a level that is unambiguously a voice, no arithmetic about floors
  // should be able to argue otherwise.
  expect(hearing(steady(CLEARLY_SPEECH_DBFS + 4))).toBe('hearing');
});

it('warns only for a voice that is genuinely there and genuinely too quiet', () => {
  // The narrow band this is allowed to speak in: risen off the floor, but not
  // far enough for a transcriber to do anything useful with it.
  expect(hearing(speech(-55, 8))).toBe('faint');
});

it('is not thrown by the gaps between words', () => {
  // Half of any window of real speech is the silence between syllables. A
  // classifier reading the latest buffer would flicker several times a second
  // on an indicator sitting in somebody's peripheral vision.
  expect(hearing(speech(-52, 22))).toBe('hearing');
});

it('waits for enough of a window before claiming anything', () => {
  // The room opens and the first buffer lands 100ms later. Announcing "barely
  // hear you" off one reading, before the presenter has drawn breath, would be
  // the screen's first act and it would be wrong.
  expect(hearing([])).toBe('silent');
  expect(hearing(steady(-20, 3))).toBe('silent');
});

it('reads nothing as nothing, and a voice as most of the way up', () => {
  // The amplitude the sound bar is drawn from. Floor-relative like everything
  // else here, so a quiet office is not read as a whisper.
  expect(loudness([])).toBe(0);
  expect(loudness(steady(-75))).toBe(0);
  expect(loudness([...steady(-52, 12), -32])).toBeGreaterThan(0.8);
});

it('never reports more than a full bar', () => {
  // Past a full bar there is nothing left to show, and an unclamped value would
  // drive a bar out of its own container.
  expect(loudness([...steady(-60, 12), -5])).toBe(1);
});

/**
 * The warning has to hold still.
 *
 * Reported from a device: "the text that says it cannot hear me keeps
 * jerking". Two causes, and the first is arithmetic. The window was written
 * believing the recorder delivered 100ms buffers; it delivers 20ms ones
 * (`uplink.FRAME_SAMPLES` is 320 at 16 kHz), so what was meant to be two
 * seconds of evidence was four hundred milliseconds of it, re-judged fifty
 * times a second.
 *
 * The second is that no window length fixes a signal sitting exactly on the
 * boundary. A warning that appears and disappears is worse than no warning, so
 * a change has to survive before it is shown.
 */

it('needs a change to hold before it will say it', () => {
  // One faint reading in a room that has been heard is a syllable boundary, not
  // a problem worth interrupting somebody about.
  let state: Steadied = { shown: 'hearing', agreeing: 0 };

  state = steadied(state, 'faint');

  expect(state.shown).toBe('hearing');
});

it('says it once the change has really held', () => {
  let state: Steadied = { shown: 'hearing', agreeing: 0 };

  for (let reading = 0; reading < STEADY_READINGS; reading += 1) {
    state = steadied(state, 'faint');
  }

  expect(state.shown).toBe('faint');
});

it('forgets a change that does not last', () => {
  // THE FLICKER. Alternating readings must accumulate nothing at all, or the
  // warning arrives on the first run of luck rather than on a real condition.
  let state: Steadied = { shown: 'hearing', agreeing: 0 };

  for (let reading = 0; reading < STEADY_READINGS * 4; reading += 1) {
    state = steadied(state, reading % 2 === 0 ? 'faint' : 'hearing');
  }

  expect(state.shown).toBe('hearing');
});

it('holds the warning up until it is properly over', () => {
  // Symmetric, deliberately. A warning that vanishes the instant one loud
  // buffer lands flickers exactly as badly as one that appears that way.
  let state: Steadied = { shown: 'faint', agreeing: 0 };

  state = steadied(state, 'hearing');
  expect(state.shown).toBe('faint');

  for (let reading = 0; reading < STEADY_READINGS; reading += 1) {
    state = steadied(state, 'hearing');
  }
  expect(state.shown).toBe('hearing');
});

it('judges two seconds of the room, not two hundred milliseconds of it', () => {
  // The arithmetic bug, stated as a property so it cannot come back: the
  // window is a duration, and it has to be derived from the buffer the
  // recorder actually delivers rather than from the one somebody remembered.
  expect(HEARD_WINDOW * BUFFER_MS).toBeGreaterThanOrEqual(1500);
  expect(ENOUGH * BUFFER_MS).toBeGreaterThanOrEqual(400);
});
