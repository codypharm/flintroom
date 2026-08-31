import { describe, expect, it } from 'vitest';

import { dilute, type DilutionInput } from './dilution';
import { dilutionQuestionsFor, STANDARD_DILUTION_QUESTIONS } from './dilution-questions';

/**
 * What to ask before you sign.
 *
 * The runway page's list runs one way — what gets asked of you. This one runs
 * the other, because dilution is negotiated rather than interrogated. The
 * tests are about tone and about firing on the right term sheet; the failure
 * mode is a list that tells a founder their pool is too big.
 */
function ask(over: Partial<DilutionInput> = {}) {
  const input: DilutionInput = {
    yourPercent: 100, safes: [], preMoney: 8_000_000, raise: 2_000_000,
    poolPercent: 0, poolPre: true, ...over,
  };
  return dilutionQuestionsFor(dilute(input), input);
}

const NOTE = { amount: 500_000, cap: 5_000_000, discountPercent: 0, kind: 'post' as const };

describe('the shape of every question', () => {
  it('asks rather than concludes', () => {
    for (const q of ask({ poolPercent: 20, safes: [NOTE] })) {
      expect(q.text.trim().endsWith('?')).toBe(true);
    }
  });

  it('never grades the term sheet', () => {
    // "Your pool is too big" is a verdict, and a verdict is the one thing no
    // Flintroom surface returns.
    const graded = /\b(too (big|high|low|much)|should be|you need to|bad deal|unfair|wrong)\b/i;

    for (const q of ask({ poolPercent: 20, safes: [NOTE, { ...NOTE, kind: 'pre' }] })) {
      expect(q.text).not.toMatch(graded);
      expect(q.why).not.toMatch(graded);
    }
  });

  it('explains who asks it and why', () => {
    for (const q of ask({ poolPercent: 20 })) {
      expect(q.why.length).toBeGreaterThan(20);
    }
  });
});

describe('the questions a term sheet invites', () => {
  it('puts a number on what moving the pool post-money would be worth', () => {
    // The counterfactual is computed, not described. "It would help" is
    // advice; "4.4 points" is an argument you can take into a room.
    const [first] = ask({ poolPercent: 15, poolPre: true });

    expect(first.id).toBe('pool-side');
    expect(first.why).toMatch(/[\d.]+ points/);
  });

  it("says nothing about the pool's side when there is no pool", () => {
    expect(ask({ poolPercent: 0 }).some((q) => q.id === 'pool-side')).toBe(false);
  });

  it('notices when the pool costs more than the money does', () => {
    const list = ask({ preMoney: 20_000_000, raise: 1_000_000, poolPercent: 15 });

    expect(list.some((q) => q.id === 'pool-outweighs')).toBe(true);
  });

  it('notices when old notes cost more than the new round', () => {
    const list = ask({ preMoney: 20_000_000, raise: 1_000_000, safes: [{ ...NOTE, cap: 3_000_000 }] });

    expect(list.some((q) => q.id === 'safes-outweigh')).toBe(true);
  });

  it('notices a mix of pre- and post-money notes', () => {
    const list = ask({ safes: [NOTE, { ...NOTE, kind: 'pre' }] });

    expect(list.some((q) => q.id === 'mixed-notes')).toBe(true);
  });

  it('does not raise the mix when every note is the same kind', () => {
    expect(ask({ safes: [NOTE, NOTE] }).some((q) => q.id === 'mixed-notes')).toBe(false);
  });

  it('notices an uncapped note carrying only a discount', () => {
    const list = ask({ safes: [{ ...NOTE, cap: 0, discountPercent: 20 }] });

    expect(list.some((q) => q.id === 'uncapped')).toBe(true);
  });

  it('raises the control line only when this round crosses it', () => {
    const crosses = ask({ yourPercent: 55, poolPercent: 10 });
    const already = ask({ yourPercent: 40 });

    expect(crosses.some((q) => q.id === 'below-half')).toBe(true);
    expect(already.some((q) => q.id === 'below-half')).toBe(false);
  });
});

describe('how many arrive at once', () => {
  it('stops short of a wall of text', () => {
    const everything = ask({
      yourPercent: 60, poolPercent: 25, preMoney: 20_000_000, raise: 1_000_000,
      safes: [{ ...NOTE, cap: 2_000_000 }, { ...NOTE, kind: 'pre', cap: 0, discountPercent: 20 }],
    });

    expect(everything.length).toBeLessThanOrEqual(7);
  });

  it('leads with the ones drawn from their own term sheet', () => {
    expect(ask({ poolPercent: 20 })[0].grounded).toBe(true);
  });

  it('has something honest to show a blank form', () => {
    expect(STANDARD_DILUTION_QUESTIONS.length).toBeGreaterThan(2);

    for (const q of STANDARD_DILUTION_QUESTIONS) {
      expect(q.grounded).toBe(false);
      expect(q.text.trim().endsWith('?')).toBe(true);
    }
  });

  it('returns no duplicates', () => {
    const ids = ask({ poolPercent: 25, safes: [NOTE, { ...NOTE, kind: 'pre' }] }).map((q) => q.id);

    expect(new Set(ids).size).toBe(ids.length);
  });
});
