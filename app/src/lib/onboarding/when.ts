/**
 * The date the room happens, and the arithmetic around it.
 *
 * Pure, and separate from the picker on purpose: the picker is two different
 * native components on two platforms (`DatePickerDialog` on Compose, an inline
 * `DatePicker` inside a `Host` on SwiftUI) and neither can be rendered by a
 * test. Everything that can be wrong without a device is in this file.
 */

/**
 * A date as `YYYY-MM-DD`, read off the local wall clock.
 *
 * **Never `toISOString().slice(0, 10)`.** That is the one-liner everybody
 * reaches for and it reports UTC: at 9pm on the 4th in New York it answers the
 * 5th, so somebody who picks "today" in the evening has their board review
 * recorded as tomorrow. The plan is a date somebody read off a calendar in the
 * room they are standing in, and it has no time and no zone.
 */
export function asIsoDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');

  return `${date.getFullYear()}-${month}-${day}`;
}

/** The inverse, at local midnight so it survives a round trip through the UI. */
export function fromIsoDate(iso: string | null): Date | null {
  if (iso === null) return null;

  const [year, month, day] = iso.split('-').map(Number);

  // The three-argument constructor is local. `new Date('2026-09-04')` is not —
  // a bare date string is parsed as UTC, which reintroduces the bug above from
  // the other direction.
  return new Date(year, month - 1, day);
}

/**
 * What the row says.
 *
 * "Not sure yet" is a real answer rather than an empty state, so it is said in
 * words and never as a placeholder or a dash — `docs/onboarding.md` is explicit
 * that a guessed date makes the countdown confidently wrong, which is worse
 * than an absent one.
 *
 * The year appears only when it is not this one. Carried always it is noise on
 * every row; carried never, a mis-scroll into next January is invisible on the
 * one line that exists to show what was chosen.
 */
export function sayWhen(iso: string | null): string {
  const date = fromIsoDate(iso);
  if (date === null) return 'Not sure yet';

  const sameYear = date.getFullYear() === new Date().getFullYear();

  return date.toLocaleDateString('en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    ...(sameYear ? {} : { year: 'numeric' }),
  });
}

/**
 * What the picker will accept.
 *
 * Today at the near end: nobody rehearses for a meeting that has already
 * happened, and a past date would put an already-negative countdown on the
 * setup screen. A year at the far end, because beyond that a date is far more
 * likely to be a mis-scroll than an answer.
 *
 * A function rather than a constant — a module evaluated once at import would
 * pin "today" to whenever the app was launched, and this app is left open.
 */
export function WINDOW(): { start: Date; end: Date } {
  const today = new Date();
  const end = new Date(today);
  end.setFullYear(end.getFullYear() + 1);

  return { start: today, end };
}
