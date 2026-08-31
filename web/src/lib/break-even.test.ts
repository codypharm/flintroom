import { describe, expect, it } from 'vitest';

import { breakEven, type BreakEvenInput } from './break-even';

/**
 * The arithmetic behind /tools/break-even-calculator.
 *
 * The standard output is a unit count, which is correct and forgettable. What
 * a business owner acts on is the day of the month the fixed costs are covered
 * and everything after starts being profit — the same move the runway page
 * makes when it gives a date instead of a number of months.
 */
function of(over: Partial<BreakEvenInput> = {}): BreakEvenInput {
  return { monthlyFixedCosts: 12_000, price: 100, grossMarginPercent: 40, monthlyVolume: 500, ...over };
}

describe('the count everybody computes', () => {
  it('divides fixed costs by what one sale contributes', () => {
    // 100 at 40% margin contributes 40. Twelve thousand of fixed costs needs
    // three hundred of them.
    const r = breakEven(of());

    expect(r.contributionPerSale).toBeCloseTo(40, 6);
    expect(r.breakEvenUnits).toBeCloseTo(300, 6);
  });

  it('states it in revenue as well, because that is how targets are set', () => {
    const r = breakEven(of());

    expect(r.breakEvenRevenue).toBeCloseTo(30_000, 6);
  });

  it('has no answer when a sale contributes nothing', () => {
    // Not an enormous number of units. There is no number of units.
    const r = breakEven(of({ grossMarginPercent: 0 }));

    expect(r.breakEvenUnits).toBeNull();
    expect(r.breakEvenRevenue).toBeNull();
  });

  it('breaks even immediately when there are no fixed costs to cover', () => {
    const r = breakEven(of({ monthlyFixedCosts: 0 }));

    expect(r.breakEvenUnits).toBe(0);
  });
});

describe('the day of the month, which is the part worth knowing', () => {
  it('says when in the month the fixed costs are covered', () => {
    // 300 of the 500 monthly sales is three fifths of the way through: day 18
    // of 30. Everything sold after that is profit.
    const r = breakEven(of());

    expect(r.breakEvenDay).toBeCloseTo(18, 0);
    expect(r.profitableDays).toBeCloseTo(12, 0);
  });

  it('arrives later as fixed costs rise', () => {
    const lean = breakEven(of({ monthlyFixedCosts: 6_000 }));
    const heavy = breakEven(of({ monthlyFixedCosts: 18_000 }));

    expect(heavy.breakEvenDay!).toBeGreaterThan(lean.breakEvenDay!);
  });

  it('has no day when the month never gets there', () => {
    // 500 sales against a break-even of 600. The answer is not "day 36".
    const r = breakEven(of({ monthlyFixedCosts: 24_000 }));

    expect(r.breakEvenDay).toBeNull();
    expect(r.reachesBreakEven).toBe(false);
  });

  it('says how many sales short it is instead', () => {
    const r = breakEven(of({ monthlyFixedCosts: 24_000 }));

    expect(r.salesShort).toBeCloseTo(100, 6);
  });

  it('is short of nothing once it does break even', () => {
    expect(breakEven(of()).salesShort).toBeNull();
  });
});

describe('how much room there is', () => {
  it('measures how far sales can fall before it stops working', () => {
    // 500 against a break-even of 300: two fifths of the volume could go.
    const r = breakEven(of());

    expect(r.marginOfSafetyPercent).toBeCloseTo(40, 6);
  });

  it('is negative when the business is under water', () => {
    // Reported rather than clamped to zero. "Twenty percent below break-even"
    // is a more useful sentence than "no margin of safety".
    const r = breakEven(of({ monthlyFixedCosts: 24_000 }));

    expect(r.marginOfSafetyPercent!).toBeLessThan(0);
  });

  it('has nothing to measure without a volume', () => {
    const r = breakEven(of({ monthlyVolume: 0 }));

    expect(r.marginOfSafetyPercent).toBeNull();
    expect(r.breakEvenDay).toBeNull();
  });
});

describe('the inputs a real form actually receives', () => {
  it('survives an empty field arriving as NaN', () => {
    const r = breakEven(of({ monthlyFixedCosts: Number.NaN, price: Number.NaN }));

    expect(Number.isFinite(r.contributionPerSale)).toBe(true);
  });

  it('treats a negative figure as nothing rather than as its opposite', () => {
    const r = breakEven(of({ monthlyFixedCosts: -5_000 }));

    expect(r.breakEvenUnits).toBe(0);
  });

  it('holds margin to a hundred', () => {
    const r = breakEven(of({ price: 100, grossMarginPercent: 250 }));

    expect(r.contributionPerSale).toBeCloseTo(100, 6);
  });
});
