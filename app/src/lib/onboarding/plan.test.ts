import { seat } from './plan';

/**
 * Filling in a seating plan by tapping it.
 *
 * The whole screen is one artifact and this is the only thing it does, so these
 * are the rules that decide whether somebody gets the room they described.
 * Order matters here in a way it does not in a picker: the server seats the
 * chips in the order they arrive, so chair one is a decision and not a set
 * membership.
 */

describe('seat', () => {
  it('puts somebody in the next free chair', () => {
    expect(seat(['budget'], 'technical', 3)).toEqual(['budget', 'technical']);
  });

  it('takes them out again when their chair is tapped', () => {
    // The same control both ways. A separate remove affordance would be a
    // second thing to find on a screen whose whole idea is that the plan is
    // directly manipulable.
    expect(seat(['budget', 'technical'], 'budget', 3)).toEqual(['technical']);
  });

  it('closes the gap rather than leaving an empty chair in the middle', () => {
    // Removing chair one must promote chair two, because the array *is* the
    // seating order. A hole would seat the next person behind somebody who is
    // no longer there.
    expect(seat(['budget', 'technical', 'ally'], 'technical', 3)).toEqual([
      'budget',
      'ally',
    ]);
  });

  it('refuses a fourth person at a three-seat table', () => {
    // Returned unchanged rather than truncated or reordered. The screen draws
    // exactly `seats` chairs, so this is only reachable by a tap on a full
    // table — and the honest answer to that is that nothing moved.
    const full = ['budget', 'technical', 'ally'];

    expect(seat(full, 'compliance', 3)).toEqual(full);
  });

  it('still lets a seated person leave a full table', () => {
    // The bug this guards: a cap checked before the toggle would make a full
    // table impossible to change at all, which is a plan somebody is locked
    // out of their own answer to.
    expect(seat(['budget', 'technical', 'ally'], 'ally', 3)).toEqual([
      'budget',
      'technical',
    ]);
  });
});
