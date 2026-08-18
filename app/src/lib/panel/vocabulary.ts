import type { WeaknessKind } from '../api/debriefApi';

/**
 * What the room's findings are called on screen, in one place.
 *
 * Two surfaces render the same weak answers — the debrief where they are worked
 * on, and the prep sheet taken into the room — and both have to agree about the
 * one thing #56 says must not be got wrong: **which findings are the
 * presenter's fault.** `dismissed` means a panelist cut across them and
 * `not_reached` means the clock ran out. Telling somebody they ducked a
 * question that was taken away from them reads as the product not having
 * listened, and a second copy of this table is how the two screens would come
 * to disagree about it — quietly, months later, when one of them is edited.
 */

/**
 * Each kind as something a person did, and whose doing it was.
 *
 * The habit is written as a verb rather than a taxonomy label: "answered a
 * different question", not "evasive". A noun invites a score; a verb invites a
 * change.
 *
 * `blame` is the load-bearing field, and nothing outside this file decides it.
 */
export const KINDS: Record<WeaknessKind, { habit: string; blame: 'them' | 'room' }> = {
  evasive: { habit: 'Answered a different question', blame: 'them' },
  unsupported: { habit: 'Claimed it without backing it', blame: 'them' },
  contradicted: { habit: 'Gave a figure that fought another one', blame: 'them' },
  unanswered: { habit: 'Let it go by', blame: 'them' },
  dismissed: { habit: 'A panelist cut across you', blame: 'room' },
  not_reached: { habit: 'The session ran out', blame: 'room' },
};

/** Archetype keys are storage; these are what a person is called. */
const PANEL: Record<string, string> = {
  cfo: 'The CFO',
  technical_skeptic: 'The Technical Skeptic',
  champion: 'The Champion',
  growth_maximalist: 'The Growth Maximalist',
  distracted: 'The Distracted Executive',
  internal_blocker: 'The Internal Blocker',
  customer_advocate: 'The Customer Advocate',
  risk_officer: 'The Risk Officer',
};

/**
 * The name, or the key when the server has an archetype this build predates.
 *
 * Falling back to the key is deliberately ugly and deliberately not blank. A
 * catalogue is fetched rather than shipped, so a new archetype can seat itself
 * in a room before any release knows what it is called — and an empty byline
 * over a real question is worse than an unpolished one.
 */
export function panelistName(key: string): string {
  return PANEL[key] ?? key;
}

/**
 * "Twice", not "2".
 *
 * A numeral in a slot built for a number reads as a metric, and a metric on
 * either of these screens is the delivery-scorer the wedge refuses
 * (`Product.md` §1). Words count without measuring, and stop counting out loud
 * past three because by then the number is not the point.
 */
export function howOften(n: number): string {
  return ['', 'once', 'twice', 'three times'][n] ?? 'again and again';
}
