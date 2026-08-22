import {
  howLongAgo,
  howLongItRan,
  pressureOf,
  theDateItRan,
  whenItRan,
  whoWasThere,
} from './rooms';

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
  it('says how long ago in the smallest unit that still means something', () => {
    // The architect's ask: "days ago or years ago or seconds ago basically diff
    // from current time along side date instead of days of the week."
    expect(howLongAgo('2026-08-20T13:59:30Z', NOW)).toBe('Just now');
    expect(howLongAgo('2026-08-20T13:45:00Z', NOW)).toBe('15 minutes ago');
    expect(howLongAgo('2026-08-20T09:12:00Z', NOW)).toBe('4 hours ago');
  });

  it('counts midnights once a day has been crossed, not elapsed hours', () => {
    // Two clocks on purpose. A room at 8:39pm read at 2pm the next day is
    // seventeen hours old and one DAY old, and "0 days ago" would be arithmetic
    // rather than English.
    expect(howLongAgo('2026-08-19T20:39:00Z', NOW)).toBe('1 day ago');
    expect(howLongAgo('2026-08-17T10:00:00Z', NOW)).toBe('3 days ago');
  });

  it('rolls up to months and then to years, because nobody holds 400 days', () => {
    expect(howLongAgo('2026-07-04T10:00:00Z', NOW)).toBe('2 months ago');
    expect(howLongAgo('2025-11-02T10:00:00Z', NOW)).toBe('10 months ago');
    expect(howLongAgo('2024-06-02T10:00:00Z', NOW)).toBe('2 years ago');
  });

  it('never says "1 days ago"', () => {
    expect(howLongAgo('2026-08-19T20:39:00Z', NOW)).toBe('1 day ago');
  });

  it('carries the year on the date once it is not this one', () => {
    expect(theDateItRan('2026-07-04T10:00:00Z', NOW)).toBe('4 July');
    expect(theDateItRan('2025-11-02T10:00:00Z', NOW)).toBe('2 November 2025');
  });

  it('says both, because they answer different questions', () => {
    // "3 days ago" places a room against the meeting you are preparing for.
    // "17 August" is how you find it again and how you refer to it to anybody
    // else. The old form gave one OR the other depending on the room's age, so
    // which answer you got depended on when you asked.
    expect(whenItRan('2026-08-17T10:00:00Z', NOW)).toBe('3 days ago · 17 August');
  });
});

describe('how long it ran', () => {
  it('gives minutes and seconds, the way a room is actually counted', () => {
    expect(howLongItRan('2026-08-20T09:12:00Z', '2026-08-20T09:23:41Z')).toBe('11:41');
  });

  it('pads the seconds so a column of rooms lines up', () => {
    expect(howLongItRan('2026-08-20T09:12:00Z', '2026-08-20T09:13:05Z')).toBe('1:05');
  });

  it('names the hour once a room has run for one', () => {
    // Reachable: a room has no length cap — the allowance is monthly minutes,
    // not minutes per room — so a long readout really can pass sixty. "90:00"
    // is a count of minutes wearing a clock's punctuation, and nobody reads it
    // as an hour and a half.
    expect(howLongItRan('2026-08-20T09:12:00Z', '2026-08-20T10:42:07Z')).toBe('1:30:07');
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
    audience: null,
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
