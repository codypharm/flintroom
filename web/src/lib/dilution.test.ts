import { describe, expect, it } from 'vitest';

import { dilute, type DilutionInput, type Safe } from './dilution';

/**
 * The arithmetic behind /tools/dilution-calculator.
 *
 * This is the one a founder will check against their own cap table, so the
 * tests below are less about coverage than about the four specific places
 * these calculators are wrong in the wild:
 *
 *   1. a post-money SAFE's percentage is fixed, so other SAFEs dilute the
 *      founders rather than each other — pre-money SAFEs dilute each other;
 *   2. cap and discount together means the holder takes whichever gives more
 *      shares, which is the LOWER effective valuation;
 *   3. a pre-money option pool dilutes existing holders only and leaves the
 *      incoming investor untouched;
 *   4. points are not percent.
 */

const ROUND = { preMoney: 8_000_000, raise: 2_000_000 };

function input(over: Partial<DilutionInput> = {}): DilutionInput {
  return {
    yourPercent: 100,
    safes: [],
    poolPercent: 0,
    poolPre: true,
    ...ROUND,
    ...over,
  };
}

function safe(over: Partial<Safe> = {}): Safe {
  return { amount: 500_000, cap: 5_000_000, discountPercent: 0, kind: 'post', ...over };
}

describe('the priced round on its own', () => {
  it('gives the investor their money over the post-money valuation', () => {
    // 2m on an 8m pre-money is 2/10 — the one piece of this every calculator
    // agrees on, and the floor everything else is measured against.
    const r = dilute(input());

    expect(r.stack.find((h) => h.who === 'investor')?.after).toBeCloseTo(20, 6);
    expect(r.yourAfter).toBeCloseTo(80, 6);
  });

  it('dilutes you in proportion to what you held, not to what you are', () => {
    // Holding 60% before means holding 60% of whatever survives. A founder
    // with co-founders is not diluted differently from one without.
    const r = dilute(input({ yourPercent: 60 }));

    expect(r.yourAfter).toBeCloseTo(48, 6);
  });

  it('reports the fall in points rather than in percent', () => {
    // 60 to 48 is twelve POINTS. It is also a twenty percent fall, and a page
    // about dilution that confuses the two is wrong in a way its readers will
    // notice and remember.
    const r = dilute(input({ yourPercent: 60 }));

    expect(r.pointsGiven).toBeCloseTo(12, 6);
  });

  it('adds up to the whole company', () => {
    const r = dilute(input({ yourPercent: 60, safes: [safe()], poolPercent: 10 }));
    const total = r.stack.reduce((sum, holding) => sum + holding.after, 0);

    expect(total).toBeCloseTo(100, 6);
  });
});

describe('a post-money SAFE', () => {
  it('takes its amount over its cap, whatever the round is priced at', () => {
    // 500k on a 5m post-money cap is 10% of the company as it stands after
    // SAFEs convert — before the new money, which then dilutes it like
    // everything else. 10% of the 80% that survives the round is 8%.
    const r = dilute(input({ safes: [safe()] }));

    expect(r.stack.find((h) => h.who === 'safes')?.after).toBeCloseTo(8, 6);
    expect(r.yourAfter).toBeCloseTo(72, 6);
  });

  it('does not let one SAFE dilute another', () => {
    // The whole reason YC replaced the pre-money SAFE in 2018. Two 10% SAFEs
    // are 20% between them, and the second one comes out of the founders.
    const r = dilute(input({ safes: [safe(), safe()] }));

    expect(r.stack.find((h) => h.who === 'safes')?.after).toBeCloseTo(16, 6);
    expect(r.yourAfter).toBeCloseTo(64, 6);
  });
});

describe('a pre-money SAFE', () => {
  it('dilutes the other SAFEs as well as the founders', () => {
    // The distinction that makes this tool worth building. The same two
    // 500k-on-5m notes leave the founders with more than the post-money pair
    // did, because here the notes eat into each other.
    const post = dilute(input({ safes: [safe(), safe()] }));
    const pre = dilute(input({ safes: [safe({ kind: 'pre' }), safe({ kind: 'pre' })] }));

    expect(pre.yourAfter).toBeGreaterThan(post.yourAfter);
  });

  it('converts at the pre-money valuation over the existing shares', () => {
    // One 500k note on a 5m cap against a 10m pre-money: the cap binds, so it
    // buys 500k/5m = 0.1 of the existing base — 1/1.1 of the company left to
    // the founders before the new money.
    const r = dilute(input({ preMoney: 10_000_000, raise: 0, safes: [safe({ kind: 'pre' })] }));

    expect(r.yourAfter).toBeCloseTo((1 / 1.1) * 100, 6);
  });
});

describe('cap against discount', () => {
  it('takes whichever gives the holder more shares', () => {
    // A 20% discount on an 8m pre-money is an effective 6.4m. A 5m cap beats
    // it. The holder gets the cap, and a calculator that averaged them or took
    // the first one listed would quietly short them.
    const capped = dilute(input({ safes: [safe({ cap: 5_000_000, discountPercent: 20 })] }));
    const capOnly = dilute(input({ safes: [safe({ cap: 5_000_000, discountPercent: 0 })] }));

    expect(capped.yourAfter).toBeCloseTo(capOnly.yourAfter, 6);
  });

  it('uses the discount when the cap is the weaker of the two', () => {
    // A 50% discount on 8m is 4m — better for the holder than a 20m cap.
    const r = dilute(input({ safes: [safe({ cap: 20_000_000, discountPercent: 50 })] }));
    const capOnly = dilute(input({ safes: [safe({ cap: 20_000_000, discountPercent: 0 })] }));

    expect(r.yourAfter).toBeLessThan(capOnly.yourAfter);
  });

  it('converts at the round price when there is neither', () => {
    // An uncapped, undiscounted SAFE is just early money at the round's own
    // price. 500k against an 8m pre-money is 500/8000 of the pre-money base.
    const r = dilute(input({ safes: [safe({ cap: 0, discountPercent: 0 })] }));

    expect(r.stack.find((h) => h.who === 'safes')?.after).toBeCloseTo((0.5 / 8) * 80, 5);
  });
});

describe('the option pool, and which side of the round it lands on', () => {
  it('leaves the incoming investor untouched when it is pre-money', () => {
    // The shuffle. The investor still gets exactly their 20%; the pool comes
    // entirely out of the people who were already there.
    const r = dilute(input({ poolPercent: 10, poolPre: true }));

    expect(r.stack.find((h) => h.who === 'investor')?.after).toBeCloseTo(20, 6);
    expect(r.stack.find((h) => h.who === 'pool')?.after).toBeCloseTo(10, 6);
    expect(r.yourAfter).toBeCloseTo(70, 6);
  });

  it('dilutes the investor too when it is post-money', () => {
    // The version a founder would prefer and rarely gets offered.
    const r = dilute(input({ poolPercent: 10, poolPre: false }));

    expect(r.stack.find((h) => h.who === 'investor')?.after).toBeCloseTo(18, 6);
    expect(r.yourAfter).toBeCloseTo(72, 6);
  });

  it('costs the founders more pre-money than post-money', () => {
    const pre = dilute(input({ poolPercent: 10, poolPre: true }));
    const post = dilute(input({ poolPercent: 10, poolPre: false }));

    expect(pre.yourAfter).toBeLessThan(post.yourAfter);
  });
});

describe('where the dilution actually came from', () => {
  it('splits the points given up between the three causes', () => {
    const r = dilute(input({ yourPercent: 100, safes: [safe()], poolPercent: 10, poolPre: true }));
    const { investor, safes, pool } = r.attribution;

    for (const points of [investor, safes, pool]) {
      expect(points).toBeGreaterThan(0);
    }
  });

  it('accounts for every point, with nothing left over', () => {
    // The attribution is the headline claim on this page. If it does not sum
    // to the total, the page is telling three small lies rather than one
    // large truth.
    const r = dilute(input({ yourPercent: 72, safes: [safe(), safe({ kind: 'pre' })], poolPercent: 12 }));
    const { investor, safes, pool } = r.attribution;

    expect(investor + safes + pool).toBeCloseTo(r.pointsGiven, 6);
  });

  it('attributes nothing to a cause that is not present', () => {
    const r = dilute(input({ poolPercent: 0, safes: [] }));

    expect(r.attribution.pool).toBe(0);
    expect(r.attribution.safes).toBe(0);
    expect(r.attribution.investor).toBeCloseTo(r.pointsGiven, 6);
  });

  it('can hand the pool a bigger share of the blame than the investor', () => {
    // The finding the page exists to surface, and the reason attribution is
    // the headline rather than the ownership figure. A big pool against a
    // small round takes more from the founders than the money does.
    const r = dilute(input({ preMoney: 20_000_000, raise: 1_000_000, poolPercent: 15, poolPre: true }));

    expect(r.attribution.pool).toBeGreaterThan(r.attribution.investor);
  });
});

describe('the inputs a real form actually receives', () => {
  it('survives an empty field arriving as NaN', () => {
    const r = dilute(input({ yourPercent: Number.NaN, poolPercent: Number.NaN }));

    expect(Number.isFinite(r.yourAfter)).toBe(true);
  });

  it('does not divide by zero when there is no round yet', () => {
    const r = dilute(input({ preMoney: 0, raise: 0 }));

    expect(Number.isFinite(r.yourAfter)).toBe(true);
    expect(r.yourAfter).toBeCloseTo(100, 6);
  });

  it('ignores a SAFE with no money in it', () => {
    const r = dilute(input({ safes: [safe({ amount: 0 })] }));

    expect(r.yourAfter).toBeCloseTo(80, 6);
  });

  it('holds a pool that would take the whole company to something possible', () => {
    const r = dilute(input({ poolPercent: 400 }));

    expect(r.yourAfter).toBeGreaterThanOrEqual(0);
  });
});
