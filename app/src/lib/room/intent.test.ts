import { intendRoom, takeIntent } from './intent';

/**
 * One tap, one room.
 *
 * `/interrogation` used to mint a metered room on mount, gated by nothing but
 * an empty dependency array. `app.json` declares the `flintroom` scheme and the
 * route sits inside `Stack.Protected guard={who === 'ready'}`, so
 * `flintroom://interrogation` started a billed room for any signed-in person
 * who tapped a link — and a remount did the same, because `Stack.Protected`
 * re-evaluates whenever `who` changes.
 *
 * The fix is not a check but a carrier: the order to open a room exists only in
 * memory, is written by the one control that starts one, and is spent on
 * arrival. A URL cannot forge it and a cold start cannot inherit it.
 */

it('will not open a room nobody asked for', () => {
  expect(takeIntent()).toBeNull();
});

it('carries the order from the tap that made it', () => {
  intendRoom({ archetypes: ['cfo', 'champion'], materialId: 'deck-1' });

  expect(takeIntent()).toEqual({
    archetypes: ['cfo', 'champion'],
    materialId: 'deck-1',
  });
});

it('is spent once, so a remount cannot re-use it', () => {
  // The path that made this a money bug rather than a routing one. A token
  // refresh flips `who` off 'ready' and back, `Stack.Protected` unmounts and
  // remounts the subtree, and the mount effect runs again on the same params.
  intendRoom({ archetypes: ['cfo'], materialId: null });

  expect(takeIntent()).not.toBeNull();
  expect(takeIntent()).toBeNull();
});

it('carries the seating itself rather than trusting the address bar', () => {
  // The seating used to travel as query params, which made the panel forgeable:
  // `flintroom://interrogation?archetypes=cfo` chose somebody's room for them,
  // and the bare link chose nothing at all — `split()` returned [] and the
  // server seated a default panel the presenter never picked.
  intendRoom({ archetypes: ['technical_skeptic'], materialId: null });

  expect(takeIntent()?.archetypes).toEqual(['technical_skeptic']);
});

it('replaces an order that was never collected rather than queueing it', () => {
  // Two taps with no room between them is one intention, not two. Queueing
  // would leave the second room opening on the first tap's seating.
  intendRoom({ archetypes: ['cfo'], materialId: null });
  intendRoom({ archetypes: ['champion'], materialId: 'deck-2' });

  expect(takeIntent()).toEqual({ archetypes: ['champion'], materialId: 'deck-2' });
  expect(takeIntent()).toBeNull();
});
