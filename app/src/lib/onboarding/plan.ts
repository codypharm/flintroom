/**
 * The seating plan somebody fills in before their first room.
 *
 * `docs/onboarding.md`'s five questions, gathered onto one artifact rather than
 * paged one to a screen. What lives here is the vocabulary and the one rule the
 * plan actually has; the component above it is layout, and the server owns what
 * any of it means — `agents/composition.py` turns these keys into archetypes,
 * and nothing in this file knows an archetype exists.
 *
 * **The keys are a wire contract, the labels are not.** `Product.md` §9 puts the
 * sentence on the client and the fact on the API, so the words below can be
 * rewritten in an app release while the keys stay put. Renaming a key is a
 * migration; renaming a label is copy.
 */

/** What kind of room this is — Q1. */
export const SITUATIONS: readonly { key: string; label: string }[] = [
  { key: 'board_review', label: 'A board or exec review' },
  { key: 'client_defense', label: 'A client meeting or a bid' },
  { key: 'roadmap_review', label: 'A roadmap or launch review' },
  { key: 'investor_pitch', label: 'An investor pitch' },
  { key: 'thesis_defense', label: 'A thesis defence or viva' },
  // Deliberately the only escape, and deliberately not a list of the rooms we
  // have not built. A picker option is a promise: naming "job interview" would
  // tell every user this product does interviews and then refuse them, and it
  // would make the reveal show a CFO to somebody who asked for a hiring
  // manager. This catches anyone off-scope without advertising anything, and
  // the count of it is the v2 demand signal `Product.md` §2 asks for.
  { key: 'other', label: 'Something else' },
];

/** What the presenter is, when they stand up — Q3. */
export const ROLES: readonly { key: string; label: string }[] = [
  { key: 'exec', label: 'Leading a function or a business' },
  { key: 'pm', label: 'Running a product or a programme' },
  { key: 'consultant', label: 'Consulting, or working for clients' },
  { key: 'founder', label: 'Founding something' },
  { key: 'student', label: 'Studying or researching' },
];

/**
 * Who is on the other side of the table — Q4, and the load-bearing question.
 *
 * Phrased as functions somebody recognises from their own meeting, never as our
 * archetypes. Nobody plans a board review by thinking "I need a Margin-Obsessed
 * CFO"; they think "whoever controls the budget". Naming these after the
 * archetypes would make the survey a panel picker and the reveal an echo —
 * somebody choosing their own room and being shown it back. The translation is
 * the payoff, and it happens on the server.
 */
export const SEATS: readonly { key: string; label: string }[] = [
  { key: 'budget', label: 'Controls the budget' },
  { key: 'technical', label: 'The technical lead' },
  { key: 'ally', label: 'Already on your side' },
  { key: 'distracted', label: 'Half-listening, wants the point' },
  { key: 'compliance', label: 'Legal, risk or compliance' },
  { key: 'customer', label: 'Speaks for the customer' },
  { key: 'rival', label: 'Loses out if you win' },
];

export function labelFor(
  vocabulary: readonly { key: string; label: string }[],
  key: string | null
): string | null {
  return vocabulary.find((entry) => entry.key === key)?.label ?? null;
}

/**
 * Tap a chair: fill it, or empty it.
 *
 * One control both ways, because the plan is directly manipulable and a
 * separate remove affordance would be a second thing to find on a screen whose
 * entire idea is that you touch the thing itself.
 *
 * Returns the audience unchanged when a full table is asked for one more. The
 * screen draws exactly `seats` chairs, so that tap means somebody wanted a
 * bigger room than their plan allows — and the honest answer is that nothing
 * moved, not a silent swap of somebody they already placed.
 */
export function seat(audience: string[], key: string, seats: number): string[] {
  // Removal is checked first, and that ordering is the rule. A cap tested
  // before the toggle would make a full table impossible to change at all,
  // locking somebody out of editing their own answer.
  if (audience.includes(key)) {
    return audience.filter((seated) => seated !== key);
  }

  if (audience.length >= seats) {
    return audience;
  }

  return [...audience, key];
}
