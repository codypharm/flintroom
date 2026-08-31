import { describe, expect, it } from 'vitest';

import { runway } from './runway';

/**
 * The arithmetic behind /tools/runway-calculator.
 *
 * Flat division is eyeballable and would not be worth a test file. Compounding
 * spend against flat revenue is not, and this page carries our name on a number
 * a founder will check against their own cap table — a wrong one here is worse
 * for the brand than no page at all.
 *
 * `from` is always passed in. Nothing in this module reads the clock, so every
 * date assertion below is a fact rather than a thing that starts failing in
 * March.
 */
const JAN = new Date('2026-01-01T00:00:00Z');

describe('the flat case, which is what everybody else computes', () => {
  it('divides cash by spend when nothing is coming in', () => {
    const r = runway({ cash: 100_000, monthlySpend: 10_000, monthlyRevenue: 0, burnGrowthPercent: 0, from: JAN });

    expect(r.months).toBe(10);
    expect(r.neverRunsOut).toBe(false);
  });

  it('divides by NET burn, because revenue is not a rounding error', () => {
    // The same 100k, but 5k a month is coming back in. A calculator that asks
    // for "burn" and means gross is the most common way these are wrong.
    const r = runway({ cash: 100_000, monthlySpend: 15_000, monthlyRevenue: 5_000, burnGrowthPercent: 0, from: JAN });

    expect(r.months).toBe(10);
  });

  it('gives back the fraction of a month, not a rounded one', () => {
    // 3.33 months is a different conversation from 3, and rounding down is
    // the kind of "conservative" that quietly makes the tool wrong.
    const r = runway({ cash: 100_000, monthlySpend: 30_000, monthlyRevenue: 0, burnGrowthPercent: 0, from: JAN });

    expect(r.months).toBeCloseTo(10 / 3, 5);
  });
});

describe('running out, as a date', () => {
  it('names the month you run out in', () => {
    // Ten whole months from 1 January is 1 November. The date is the output
    // that gets acted on; the month count is the one that gets quoted.
    const r = runway({ cash: 100_000, monthlySpend: 10_000, monthlyRevenue: 0, burnGrowthPercent: 0, from: JAN });

    expect(r.endsOn?.getUTCFullYear()).toBe(2026);
    expect(r.endsOn?.getUTCMonth()).toBe(10); // November
    expect(r.endsOn?.getUTCDate()).toBe(1);
  });

  it('carries the fraction into days rather than dropping it', () => {
    // 3⅓ months from 1 January: through March, then a third of April.
    const r = runway({ cash: 90_000, monthlySpend: 27_000, monthlyRevenue: 0, burnGrowthPercent: 0, from: JAN });

    expect(r.months).toBeCloseTo(10 / 3, 5);
    expect(r.endsOn?.getUTCMonth()).toBe(3); // April
    expect(r.endsOn?.getUTCDate()).toBeGreaterThan(1);
  });

  it('crosses a year boundary without losing a month', () => {
    const r = runway({ cash: 180_000, monthlySpend: 10_000, monthlyRevenue: 0, burnGrowthPercent: 0, from: JAN });

    expect(r.months).toBe(18);
    expect(r.endsOn?.getUTCFullYear()).toBe(2027);
    expect(r.endsOn?.getUTCMonth()).toBe(6); // July
  });
});

describe('growing spend, which is the whole reason this page exists', () => {
  it('runs out sooner than the division says', () => {
    const flat = runway({ cash: 120_000, monthlySpend: 10_000, monthlyRevenue: 0, burnGrowthPercent: 0, from: JAN });
    const growing = runway({ cash: 120_000, monthlySpend: 10_000, monthlyRevenue: 0, burnGrowthPercent: 5, from: JAN });

    expect(flat.months).toBe(12);
    expect(growing.months).toBeLessThan(12);
  });

  it('compounds month on month rather than adding a flat amount', () => {
    // 10% growth on 10k is 11,000 then 12,100 — not 11,000 then 12,000. The
    // difference is invisible at month two and enormous at month twenty, which
    // is exactly the kind of error nobody catches by looking.
    const r = runway({ cash: 1_000_000, monthlySpend: 10_000, monthlyRevenue: 0, burnGrowthPercent: 10, from: JAN });

    expect(r.schedule[0].spend).toBeCloseTo(10_000, 5);
    expect(r.schedule[1].spend).toBeCloseTo(11_000, 5);
    expect(r.schedule[2].spend).toBeCloseTo(12_100, 5);
  });

  it('runs out eventually even when revenue starts ahead of spend', () => {
    // Profitable today, spending more every month, revenue flat. This is the
    // case a flat calculator calls infinite and a board meeting does not.
    const r = runway({ cash: 200_000, monthlySpend: 10_000, monthlyRevenue: 12_000, burnGrowthPercent: 8, from: JAN });

    expect(r.neverRunsOut).toBe(false);
    expect(r.months).toBeGreaterThan(12);
  });
});

describe('when it does not run out', () => {
  it('says so rather than returning a very large number', () => {
    const r = runway({ cash: 100_000, monthlySpend: 8_000, monthlyRevenue: 12_000, burnGrowthPercent: 0, from: JAN });

    expect(r.neverRunsOut).toBe(true);
    expect(r.endsOn).toBeNull();
  });

  it('treats breaking exactly even as not running out', () => {
    // Net burn of zero. Dividing by it is the obvious bug, and the answer is
    // not "infinity months", it is "this does not end".
    const r = runway({ cash: 100_000, monthlySpend: 10_000, monthlyRevenue: 10_000, burnGrowthPercent: 0, from: JAN });

    expect(r.neverRunsOut).toBe(true);
    expect(r.months).toBe(Infinity);
  });
});

describe('the inputs a real form actually receives', () => {
  it('reports no runway when there is no cash', () => {
    const r = runway({ cash: 0, monthlySpend: 10_000, monthlyRevenue: 0, burnGrowthPercent: 0, from: JAN });

    expect(r.months).toBe(0);
    expect(r.endsOn?.getTime()).toBe(JAN.getTime());
  });

  it('treats a negative balance as no runway, not as negative runway', () => {
    const r = runway({ cash: -5_000, monthlySpend: 10_000, monthlyRevenue: 0, burnGrowthPercent: 0, from: JAN });

    expect(r.months).toBe(0);
  });

  it('survives an empty field arriving as NaN', () => {
    // `Number("")` is 0 but `parseFloat("")` is NaN, and a page whose result
    // reads "NaN months" is worse than one that refuses.
    const r = runway({ cash: Number.NaN, monthlySpend: 10_000, monthlyRevenue: 0, burnGrowthPercent: 0, from: JAN });

    expect(r.months).toBe(0);
  });

  it('does not let a negative growth rate turn spend negative', () => {
    // Somebody will type -50 to model cuts. Compounding that far enough makes
    // spend approach zero, which is fine — it must never cross it and start
    // paying money in.
    const r = runway({ cash: 100_000, monthlySpend: 10_000, monthlyRevenue: 0, burnGrowthPercent: -50, from: JAN });

    for (const month of r.schedule) {
      expect(month.spend).toBeGreaterThanOrEqual(0);
    }
  });
});

describe('the month-by-month strip', () => {
  it('closes each month on the balance the next one opens with', () => {
    const r = runway({ cash: 100_000, monthlySpend: 10_000, monthlyRevenue: 2_000, burnGrowthPercent: 3, from: JAN });

    let expected = 100_000;
    for (const month of r.schedule) {
      expected -= month.spend - month.revenue;
      expect(month.closing).toBeCloseTo(Math.max(expected, 0), 5);
    }
  });

  it('stops at the month the money does, rather than showing negative cash', () => {
    const r = runway({ cash: 25_000, monthlySpend: 10_000, monthlyRevenue: 0, burnGrowthPercent: 0, from: JAN });

    expect(r.schedule).toHaveLength(3);
    expect(r.schedule.at(-1)?.closing).toBe(0);
  });

  it('is bounded, so a nearly-infinite runway cannot render forever', () => {
    const r = runway({ cash: 10_000_000, monthlySpend: 1_000, monthlyRevenue: 0, burnGrowthPercent: 0, from: JAN });

    expect(r.schedule.length).toBeLessThanOrEqual(60);
  });
});

describe('growing revenue, and the question every investor actually asks', () => {
  it('lasts longer when revenue is climbing', () => {
    const flat = runway({ cash: 100_000, monthlySpend: 20_000, monthlyRevenue: 5_000, burnGrowthPercent: 0, from: JAN });
    const climbing = runway({
      cash: 100_000, monthlySpend: 20_000, monthlyRevenue: 5_000,
      burnGrowthPercent: 0, revenueGrowthPercent: 10, from: JAN,
    });

    expect(climbing.months).toBeGreaterThan(flat.months);
  });

  it('defaults revenue to flat, because that is the honest floor', () => {
    // Omitting the field must mean "I am not claiming growth", never "assume
    // some". A calculator that quietly assumes growth flatters every user.
    const stated = runway({
      cash: 100_000, monthlySpend: 20_000, monthlyRevenue: 5_000,
      burnGrowthPercent: 0, revenueGrowthPercent: 0, from: JAN,
    });
    const omitted = runway({ cash: 100_000, monthlySpend: 20_000, monthlyRevenue: 5_000, burnGrowthPercent: 0, from: JAN });

    expect(omitted.months).toBe(stated.months);
  });

  it('is default alive when revenue overtakes spend before the cash goes', () => {
    // Paul Graham's definition, and the one question on every diligence list:
    // on the current trajectory and with no new money, do you get to
    // profitable before you get to zero.
    const r = runway({
      cash: 300_000, monthlySpend: 20_000, monthlyRevenue: 10_000,
      burnGrowthPercent: 0, revenueGrowthPercent: 15, from: JAN,
    });

    expect(r.defaultAlive).toBe(true);
    expect(r.profitableFrom).toBeGreaterThan(0);
    expect(r.neverRunsOut).toBe(true);
  });

  it('is default dead when the crossover comes after the money does', () => {
    // Growing, genuinely on its way to profitable, and it does not get there:
    // 3% a month needs about two years to close a 2x gap, and there is four
    // months of cash. This is the case a flat calculator and an optimistic
    // founder both miss.
    //
    // The first version of this test used 15% growth and asserted the same
    // thing, which was simply wrong — at 15% the crossover lands in month six
    // and the business survives. Worth keeping the note: the interesting
    // boundary here is growth rate against months of cash, and eyeballing it
    // is exactly what this file exists to stop.
    const r = runway({
      cash: 40_000, monthlySpend: 20_000, monthlyRevenue: 10_000,
      burnGrowthPercent: 0, revenueGrowthPercent: 3, from: JAN,
    });

    expect(r.defaultAlive).toBe(false);
    expect(r.months).toBeLessThan(12);
  });

  it('is not default alive merely for being rich', () => {
    // Enormous cash, tiny burn, no revenue at all. It does not run out inside
    // any horizon worth simulating, and it is still default dead — nothing in
    // it ever becomes profitable. Conflating the two would be the easy bug.
    const r = runway({ cash: 50_000_000, monthlySpend: 1_000, monthlyRevenue: 0, burnGrowthPercent: 0, from: JAN });

    expect(r.neverRunsOut).toBe(true);
    expect(r.defaultAlive).toBe(false);
    expect(r.profitableFrom).toBeNull();
  });

  it('counts a business already in the black as default alive from month one', () => {
    const r = runway({ cash: 100_000, monthlySpend: 8_000, monthlyRevenue: 12_000, burnGrowthPercent: 0, from: JAN });

    expect(r.defaultAlive).toBe(true);
    expect(r.profitableFrom).toBe(1);
  });

  it('is default dead when spend grows faster than revenue', () => {
    // Both climbing, spend climbing harder. The lines never cross, so there is
    // no month where this pays for itself however long you wait.
    const r = runway({
      cash: 500_000, monthlySpend: 20_000, monthlyRevenue: 18_000,
      burnGrowthPercent: 10, revenueGrowthPercent: 4, from: JAN,
    });

    expect(r.defaultAlive).toBe(false);
    expect(r.profitableFrom).toBeNull();
  });
});
