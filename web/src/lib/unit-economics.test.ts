import { describe, expect, it } from 'vitest';

import { unitEconomics, type UnitEconomicsInput } from './unit-economics';

/**
 * The arithmetic behind /tools/ltv-cac-calculator.
 *
 * The ratio is the number people quote and the softest thing in the deck,
 * because LTV assumes a customer lifetime nobody has lived yet. So the tests
 * that matter here are the ones about that assumption: how long the lifetime
 * implies, whether the company has existed that long, and the churn unit —
 * which is where these calculators are wrong by a factor of ten rather than a
 * few percent.
 */
function of(over: Partial<UnitEconomicsInput> = {}): UnitEconomicsInput {
  return {
    monthlyRevenuePerCustomer: 100,
    grossMarginPercent: 70,
    monthlyChurnPercent: 3,
    cac: 500,
    monthsOperating: 14,
    ...over,
  };
}

describe('what a customer is actually worth', () => {
  it('values them at gross profit, not revenue', () => {
    // A customer paying 100 a month at 70% margin is worth 70 a month to you.
    // Every calculator that skips this is computing revenue and calling it
    // value — the same shape of error as gross burn against net.
    const r = unitEconomics(of());

    expect(r.monthlyContribution).toBeCloseTo(70, 6);
  });

  it('derives the lifetime from churn, and it is one over churn', () => {
    // 3% a month means the average customer stays 33 months. That figure is
    // the whole page: it is an assumption stated as a duration.
    const r = unitEconomics(of());

    expect(r.averageLifetimeMonths).toBeCloseTo(100 / 3, 6);
  });

  it('multiplies the two into LTV', () => {
    const r = unitEconomics(of());

    expect(r.ltv).toBeCloseTo(70 / 0.03, 4);
  });

  it('reports zero value when nothing is left after cost of sale', () => {
    const r = unitEconomics(of({ grossMarginPercent: 0 }));

    expect(r.ltv).toBe(0);
  });
});

describe('the ratio, and the cash question underneath it', () => {
  it('divides value by what it cost to buy', () => {
    const r = unitEconomics(of());

    expect(r.ratio).toBeCloseTo(70 / 0.03 / 500, 4);
  });

  it('says how many months until the acquisition is paid back', () => {
    // 500 to acquire, 70 a month coming back: a little over seven months.
    // This is the cash statement, and the ratio is the profitability one — a
    // company can have an excellent ratio and a fatal payback.
    const r = unitEconomics(of());

    expect(r.paybackMonths).toBeCloseTo(500 / 70, 6);
  });

  it('has no payback when a customer contributes nothing', () => {
    // Not "infinite months" and certainly not zero. It does not pay back.
    const r = unitEconomics(of({ grossMarginPercent: 0 }));

    expect(r.paybackMonths).toBeNull();
  });

  it('has no ratio when nothing was spent to acquire anybody', () => {
    const r = unitEconomics(of({ cac: 0 }));

    expect(r.ratio).toBeNull();
  });
});

describe('the churn unit, which is where the factor-of-ten errors live', () => {
  it('translates monthly churn into the annual figure', () => {
    // 3% a month is about 31% a year, not 3%. Quoting one and meaning the
    // other is the most common way a ratio ends up an order of magnitude out.
    const r = unitEconomics(of({ monthlyChurnPercent: 3 }));

    expect(r.annualChurnPercent).toBeCloseTo((1 - 0.97 ** 12) * 100, 4);
  });

  it('compounds rather than multiplying by twelve', () => {
    // 5% a month is 46% a year, not 60%. A calculator that multiplies is
    // wrong in the pessimistic direction, which is no better.
    const r = unitEconomics(of({ monthlyChurnPercent: 5 }));

    expect(r.annualChurnPercent).toBeCloseTo(45.96, 1);
    expect(r.annualChurnPercent).toBeLessThan(60);
  });

  it('treats losing everybody every month as a one-month lifetime', () => {
    const r = unitEconomics(of({ monthlyChurnPercent: 100 }));

    expect(r.averageLifetimeMonths).toBeCloseTo(1, 6);
    expect(r.annualChurnPercent).toBeCloseTo(100, 6);
  });

  it('refuses to pretend zero churn is a number', () => {
    // Nobody ever leaving means an infinite lifetime and an infinite LTV. It
    // is not a good result, it is an unfilled field, and a page reporting a
    // huge ratio there would be flattering somebody into nonsense.
    const r = unitEconomics(of({ monthlyChurnPercent: 0 }));

    expect(r.averageLifetimeMonths).toBeNull();
    expect(r.ltv).toBeNull();
    expect(r.ratio).toBeNull();
  });
});

describe('the assumption the page exists to name', () => {
  it('notices when the assumed lifetime outruns the company', () => {
    // 33 months of assumed lifetime against 14 months of existing. The
    // headline: you are quoting a number that depends on customers behaving
    // for longer than you have been able to observe anybody.
    const r = unitEconomics(of({ monthsOperating: 14 }));

    expect(r.lifetimeExceedsHistory).toBe(true);
  });

  it('does not raise it when the company has been around longer', () => {
    const r = unitEconomics(of({ monthsOperating: 60 }));

    expect(r.lifetimeExceedsHistory).toBe(false);
  });

  it('says nothing either way when the lifetime is unknown', () => {
    const r = unitEconomics(of({ monthlyChurnPercent: 0 }));

    expect(r.lifetimeExceedsHistory).toBe(false);
  });

  it('says nothing when nobody has said how long they have been going', () => {
    const r = unitEconomics(of({ monthsOperating: 0 }));

    expect(r.lifetimeExceedsHistory).toBe(false);
  });
});

describe('the inputs a real form actually receives', () => {
  it('survives an empty field arriving as NaN', () => {
    const r = unitEconomics(of({ monthlyRevenuePerCustomer: Number.NaN, cac: Number.NaN }));

    expect(Number.isFinite(r.monthlyContribution)).toBe(true);
  });

  it('treats a negative figure as nothing rather than as its opposite', () => {
    const r = unitEconomics(of({ monthlyRevenuePerCustomer: -100 }));

    expect(r.monthlyContribution).toBe(0);
  });

  it('holds churn to something that can happen', () => {
    const r = unitEconomics(of({ monthlyChurnPercent: 400 }));

    expect(r.averageLifetimeMonths).toBeGreaterThanOrEqual(1);
  });

  it('holds margin to a hundred, because you cannot keep more than you charge', () => {
    const r = unitEconomics(of({ grossMarginPercent: 250 }));

    expect(r.monthlyContribution).toBeCloseTo(100, 6);
  });
});
