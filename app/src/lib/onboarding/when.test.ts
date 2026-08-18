import { asIsoDate, fromIsoDate, sayWhen, WINDOW } from './when';

describe('asIsoDate', () => {
  it('reads the date off the wall clock, not off UTC', () => {
    // THE BUG THIS EXISTS TO PREVENT. `toISOString().slice(0, 10)` is the
    // obvious one-liner and it is wrong for most of the planet: 9pm on the 4th
    // in New York is already the 5th in UTC, so somebody picking "today" in the
    // evening would have their board review recorded as tomorrow.
    const evening = new Date(2026, 8, 4, 21, 30);

    expect(asIsoDate(evening)).toBe('2026-09-04');
  });

  it('pads a single-digit month and day', () => {
    expect(asIsoDate(new Date(2026, 0, 7))).toBe('2026-01-07');
  });
});

describe('fromIsoDate', () => {
  it('returns a date at local midnight, so it survives the round trip', () => {
    const back = fromIsoDate('2026-09-04');

    expect(back).not.toBeNull();
    expect(asIsoDate(back as Date)).toBe('2026-09-04');
  });

  it('answers null for an answer that was never given', () => {
    expect(fromIsoDate(null)).toBeNull();
  });
});

describe('sayWhen', () => {
  it('says the day, because a date is read at a glance and 2026-09-04 is not', () => {
    // Asserted in parts rather than as one string. The month's short form is
    // ICU's to decide — en-GB says "Sept", not "Sep" — and pinning the exact
    // output makes this fail on an ICU upgrade that broke nothing.
    const said = sayWhen('2026-09-04');

    expect(said).toMatch(/^Fri\b/);
    expect(said).toMatch(/\b4\b/);
    expect(said).toMatch(/Sep/);
    expect(said).not.toMatch(/2026/);
  });

  it('keeps the year when it is not this one', () => {
    // Without it, a mis-scroll into next year is invisible on the row that is
    // supposed to be showing what was chosen.
    const nextYear = new Date().getFullYear() + 1;

    expect(sayWhen(`${nextYear}-01-09`)).toMatch(String(nextYear));
  });

  it('treats no date as the answer it is', () => {
    expect(sayWhen(null)).toBe('Not sure yet');
  });
});

describe('WINDOW', () => {
  it('does not offer a date in the past', () => {
    // Nobody rehearses for a meeting that has happened. A past date is a
    // mis-scroll, and accepting it would put a countdown on the setup screen
    // that is already negative.
    const today = new Date();

    expect(asIsoDate(WINDOW().start)).toBe(asIsoDate(today));
  });

  it('reaches a year out and no further', () => {
    expect(WINDOW().end.getFullYear()).toBe(new Date().getFullYear() + 1);
  });
});
