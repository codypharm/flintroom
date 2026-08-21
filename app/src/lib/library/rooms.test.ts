import { howLongItRan, pressureOf, whenItRan, whoWasThere } from './rooms';

/**
 * A past room, said the way somebody would say it.
 *
 * The Library is the first screen in this product that is about a *history*
 * rather than about one room, and history is where a timestamp stops being data
 * and becomes "yesterday". Everything here is the difference between a record
 * and a sentence.
 */

// A Thursday, so "yesterday" and "last week" are unambiguous.
const NOW = new Date('2026-08-20T14:00:00Z');

describe('when it ran', () => {
  it('says today rather than a date, for the room you just left', () => {
    // The commonest row by a wide margin: the debrief hands you here, and the
    // room you are looking for is the one you were in ninety seconds ago.
    expect(whenItRan('2026-08-20T09:12:00Z', NOW)).toBe('Today');
  });

  it('says yesterday, which nobody reads as a date', () => {
    expect(whenItRan('2026-08-19T20:39:00Z', NOW)).toBe('Yesterday');
  });

  it('names the day inside the last week, because that is how people place it', () => {
    // "Monday" locates a rehearsal better than "17 August" does when it is
    // still inside the week you are living in.
    expect(whenItRan('2026-08-17T10:00:00Z', NOW)).toBe('Monday');
  });

  it('falls back to the date once the day name stops meaning anything', () => {
    // Past a week, "Monday" is ambiguous — it could be any Monday — so the
    // date is the more useful answer rather than the more formal one.
    expect(whenItRan('2026-07-04T10:00:00Z', NOW)).toBe('4 July');
  });

  it('carries the year once it is not this one', () => {
    expect(whenItRan('2025-11-02T10:00:00Z', NOW)).toBe('2 November 2025');
  });
});

describe('how long it ran', () => {
  it('gives minutes and seconds, the way a room is actually counted', () => {
    expect(howLongItRan('2026-08-20T09:12:00Z', '2026-08-20T09:23:41Z')).toBe('11:41');
  });

  it('pads the seconds so a column of rooms lines up', () => {
    expect(howLongItRan('2026-08-20T09:12:00Z', '2026-08-20T09:13:05Z')).toBe('1:05');
  });

  it('says nothing at all about a room that never settled', () => {
    // Reachable and ordinary: a room that failed to provision has a start and
    // no end. A zero would be a claim that it ran for no time, which is a
    // different and wrong statement.
    expect(howLongItRan('2026-08-20T09:12:00Z', null)).toBeNull();
  });
});

describe('who was there', () => {
  it('names them the way the rest of the product names them', () => {
    // Through the same table the debrief and the prep sheet read. A second
    // spelling of "The CFO" is how two screens come to disagree quietly.
    expect(whoWasThere(['cfo', 'champion'])).toBe('The CFO and The Champion');
  });

  it('joins three or more without an inventory comma at the end', () => {
    expect(whoWasThere(['cfo', 'champion', 'technical_skeptic'])).toBe(
      'The CFO, The Champion and The Technical Skeptic'
    );
  });

  it('says who was there even when nobody was', () => {
    // A room that failed before seating. Saying nothing leaves a blank line
    // where the panel should be, which reads as a rendering fault rather than
    // as a room that never opened.
    expect(whoWasThere([])).toBe('Nobody was seated');
  });
});

describe('the pressure a rehearsal is running at', () => {
  const AT = (id: string, rehearsalId: string, startedAt: string, level: number | null) => ({
    id,
    rehearsalId,
    rehearsalName: null,
    state: 'settled',
    startedAt,
    endReason: 'user_ended',
    settledAt: startedAt,
    archetypes: ['cfo'],
    materialIds: [],
    difficultyLevel: level,
    recording: { state: 'not_recorded' as const, expiresAt: null },
  });

  it('is the rung the newest attempt actually ran at', () => {
    // "Run it again" restores the panel and the deck; it has to restore the
    // pressure too, or the button hands back a different room than it names.
    // The setup screen shows this so it cannot state one rung and start another.
    expect(
      pressureOf(
        [
          AT('b', 'a', '2026-08-20T09:00:00Z', 3),
          AT('a', 'a', '2026-08-11T09:00:00Z', 1),
        ],
        'a'
      )
    ).toBe(3);
  });

  it('ignores rooms belonging to a different rehearsal', () => {
    // The whole point. A badly handled demo day must not decide how hard the
    // board readout presses.
    expect(
      pressureOf(
        [
          AT('z', 'z', '2026-08-20T09:00:00Z', 1),
          AT('a', 'a', '2026-08-11T09:00:00Z', 3),
        ],
        'a'
      )
    ).toBe(3);
  });

  it('skips a room that never became one', () => {
    // A session that failed to provision has no rung, because there was no
    // room. Inheriting a null would be inheriting nothing and reading as zero.
    expect(
      pressureOf(
        [
          AT('b', 'a', '2026-08-20T09:00:00Z', null),
          AT('a', 'a', '2026-08-11T09:00:00Z', 2),
        ],
        'a'
      )
    ).toBe(2);
  });

  it('says nothing about a rehearsal that has never run', () => {
    // Null, so the screen falls back to the account's rung rather than
    // inventing a number for a rehearsal with nothing behind it.
    expect(pressureOf([AT('a', 'a', '2026-08-11T09:00:00Z', null)], 'a')).toBeNull();
  });
});
