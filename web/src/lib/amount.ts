/**
 * Reading and writing the numbers on a calculator page.
 *
 * The fields are `type="text"` with `inputmode="decimal"` rather than
 * `type="number"`, so that "600,000" pasted out of a spreadsheet is accepted
 * rather than silently rejected by the browser. That choice moves the parsing
 * here, which is where it can be tested.
 *
 * No currency anywhere, deliberately. Runway is a ratio — cash over burn — so
 * the symbol contributes nothing to the arithmetic, and picking one would make
 * the page quietly American for everybody it is not.
 */

/**
 * A figure as a person types or pastes it.
 *
 * Returns `NaN` for an empty or unparseable field rather than a confident zero:
 * a blank cash box reported as "0 months" reads like an answer when it is an
 * absence. `runway` treats `NaN` as nothing, so the refusal survives the trip.
 */
export function parseAmount(raw: string): number {
  const cleaned = raw.replace(/[^0-9.\-]/g, '');
  if (cleaned === '' || cleaned === '-' || cleaned === '.') return Number.NaN;

  const value = Number(cleaned);
  return Number.isFinite(value) ? value : Number.NaN;
}

/** Grouped thousands, whole units. The figure is meant to be read aloud. */
export function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value);
}

/**
 * The month, never the day.
 *
 * The simulation does produce a day, and printing it would be a claim of
 * precision that compounding assumptions cannot support — somebody would quote
 * it back to a room.
 */
export function formatMonth(date: Date): string {
  return new Intl.DateTimeFormat('en-GB', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(date);
}

/**
 * What the field is allowed to contain while somebody is typing in it.
 *
 * `type="text"` is what lets a pasted "$600,000" survive where `type="number"`
 * would silently reject it — and it is also what lets somebody type "abc".
 * Filtering on the way in beats validating on the way out: there is no invalid
 * state, so there is no error message to write and none to read.
 *
 * Thousands separators are kept rather than stripped. Removing them mid-word
 * moves the caret and fights the person using the field; the value is
 * normalised when they leave it instead.
 *
 * A minus is allowed only where it means something. Modelling a 20% cut is a
 * real thing to do; negative cash in the bank is not something this page can
 * say anything useful about.
 */
export function sanitizeTyping(raw: string, options: { negative: boolean }): string {
  const negative = options.negative && raw.trimStart().startsWith('-');

  let seenDot = false;
  const body = raw
    .replace(/[^0-9., ]/g, '')
    .split('')
    .filter((character) => {
      if (character !== '.') return true;
      if (seenDot) return false;
      seenDot = true;
      return true;
    })
    .join('');

  return negative ? `-${body}` : body;
}

/**
 * A growth rate a business could actually have, applied when the field is left.
 *
 * Below -100% the line would cross zero and start paying money in. Above +100%
 * a month is not a rate, it is a typo — and either one produces a runway figure
 * that looks authoritative and means nothing.
 */
export function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(100, Math.max(-100, value));
}

/** One decimal, because 3.3 months is a different conversation from 3. */
export function formatMonths(months: number): string {
  const rounded = Math.round(months * 10) / 10;
  const shown = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);

  return `${shown} ${rounded === 1 ? 'month' : 'months'}`;
}
