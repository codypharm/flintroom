import { describe, expect, it } from 'vitest';

import { businessCase, type RoiInput } from './roi';

/**
 * The arithmetic behind /tools/roi-calculator.
 *
 * The headline of that page is not the ROI figure, it is the break-even
 * benefit: the fraction of the projected upside at which the case stops
 * paying for itself. So most of what is asserted here is that one number
 * behaves — it is what an executive will quote in a room, and it is the
 * answer to the question every business case actually gets asked.
 */
function of(over: Partial<RoiInput> = {}): RoiInput {
  return {
    oneOffCost: 0,
    monthlyCost: 0,
    monthlyBenefit: 0,
    rampMonths: 0,
    horizonMonths: 12,
    discountRatePercent: 0,
    ...over,
  };
}

describe('the simple case, with no ramp and no discounting', () => {
  it('totals the cost and the benefit over the horizon', () => {
    const r = businessCase(of({ oneOffCost: 10_000, monthlyCost: 1_000, monthlyBenefit: 3_000 }));

    expect(r.totalCost).toBe(22_000);
    expect(r.totalBenefit).toBe(36_000);
    expect(r.netBenefit).toBe(14_000);
  });

  it('states return against what was spent', () => {
    // 14,000 back on 22,000 spent.
    const r = businessCase(of({ oneOffCost: 10_000, monthlyCost: 1_000, monthlyBenefit: 3_000 }));

    expect(r.roiPercent).toBeCloseTo((14_000 / 22_000) * 100, 6);
  });

  it('finds the month the case turns positive', () => {
    // 10,000 down, then 2,000 a month of net benefit: five months to level.
    const r = businessCase(of({ oneOffCost: 10_000, monthlyCost: 1_000, monthlyBenefit: 3_000 }));

    expect(r.paybackMonths).toBeCloseTo(5, 6);
  });

  it('carries the fraction of the month it pays back in', () => {
    const r = businessCase(of({ oneOffCost: 5_000, monthlyCost: 0, monthlyBenefit: 2_000 }));

    expect(r.paybackMonths).toBeCloseTo(2.5, 6);
  });

  it('says so plainly when it never pays back inside the horizon', () => {
    // Never returning is a finding, not a very large number.
    const r = businessCase(of({ oneOffCost: 100_000, monthlyCost: 0, monthlyBenefit: 1_000 }));

    expect(r.paybackMonths).toBeNull();
  });
});

describe('the ramp, because nothing arrives at full benefit on day one', () => {
  it('climbs to the run rate over the months given', () => {
    const r = businessCase(of({ monthlyBenefit: 3_000, rampMonths: 3, horizonMonths: 4 }));

    expect(r.schedule[0].benefit).toBeCloseTo(1_000, 6);
    expect(r.schedule[1].benefit).toBeCloseTo(2_000, 6);
    expect(r.schedule[2].benefit).toBeCloseTo(3_000, 6);
    expect(r.schedule[3].benefit).toBeCloseTo(3_000, 6);
  });

  it('pushes payback later than the no-ramp version', () => {
    const flat = businessCase(of({ oneOffCost: 10_000, monthlyBenefit: 3_000, horizonMonths: 24 }));
    const ramped = businessCase(of({ oneOffCost: 10_000, monthlyBenefit: 3_000, rampMonths: 6, horizonMonths: 24 }));

    expect(ramped.paybackMonths!).toBeGreaterThan(flat.paybackMonths!);
  });

  it('starts at the run rate when no ramp is given', () => {
    const r = businessCase(of({ monthlyBenefit: 3_000, rampMonths: 0, horizonMonths: 2 }));

    expect(r.schedule[0].benefit).toBeCloseTo(3_000, 6);
  });

  it('never reaches full benefit when the ramp outlasts the horizon', () => {
    const r = businessCase(of({ monthlyBenefit: 3_000, rampMonths: 24, horizonMonths: 6 }));

    expect(r.schedule.at(-1)!.benefit).toBeLessThan(3_000);
  });
});

describe('discounting', () => {
  it('leaves the net alone at a rate of zero', () => {
    const r = businessCase(of({ oneOffCost: 10_000, monthlyBenefit: 2_000, horizonMonths: 12 }));

    expect(r.npv).toBeCloseTo(r.netBenefit, 6);
  });

  it('values later money at less than the same money now', () => {
    const flat = businessCase(of({ oneOffCost: 10_000, monthlyBenefit: 2_000, horizonMonths: 24 }));
    const discounted = businessCase(
      of({ oneOffCost: 10_000, monthlyBenefit: 2_000, horizonMonths: 24, discountRatePercent: 10 }),
    );

    expect(discounted.npv).toBeLessThan(flat.npv);
  });

  it('takes the one-off cost at face value, because it is paid today', () => {
    // Discounting money you are about to spend is the classic sign error in a
    // hand-rolled NPV.
    const r = businessCase(of({ oneOffCost: 10_000, horizonMonths: 12, discountRatePercent: 25 }));

    expect(r.npv).toBeCloseTo(-10_000, 6);
  });
});

describe('the break-even benefit — what the page leads with', () => {
  it('is the share of the projected upside that has to land', () => {
    // 24,000 of cost against 48,000 of projected benefit: half of it is
    // enough. This is the number an executive quotes in the room.
    const r = businessCase(of({ oneOffCost: 24_000, monthlyBenefit: 4_000, horizonMonths: 12 }));

    expect(r.breakEvenBenefitPercent).toBeCloseTo(50, 6);
  });

  it('counts the recurring cost as well as the one-off', () => {
    const r = businessCase(of({ oneOffCost: 12_000, monthlyCost: 1_000, monthlyBenefit: 4_000, horizonMonths: 12 }));

    expect(r.breakEvenBenefitPercent).toBeCloseTo((24_000 / 48_000) * 100, 6);
  });

  it('goes above a hundred when the case does not pay back at all', () => {
    // Saying "you need 140% of the projected benefit" is more useful, and more
    // honest, than clamping it to 100 and implying it is close.
    const r = businessCase(of({ oneOffCost: 100_000, monthlyBenefit: 4_000, horizonMonths: 12 }));

    expect(r.breakEvenBenefitPercent!).toBeGreaterThan(100);
  });

  it('rises once the money is discounted, because the benefit arrives later than the cost', () => {
    const flat = businessCase(of({ oneOffCost: 24_000, monthlyBenefit: 4_000, horizonMonths: 12 }));
    const discounted = businessCase(
      of({ oneOffCost: 24_000, monthlyBenefit: 4_000, horizonMonths: 12, discountRatePercent: 15 }),
    );

    expect(discounted.breakEvenBenefitPercent!).toBeGreaterThan(flat.breakEvenBenefitPercent!);
  });

  it('rises with a ramp, because less of the benefit lands inside the horizon', () => {
    const flat = businessCase(of({ oneOffCost: 24_000, monthlyBenefit: 4_000, horizonMonths: 12 }));
    const ramped = businessCase(of({ oneOffCost: 24_000, monthlyBenefit: 4_000, rampMonths: 6, horizonMonths: 12 }));

    expect(ramped.breakEvenBenefitPercent!).toBeGreaterThan(flat.breakEvenBenefitPercent!);
  });

  it('has no answer when there is no benefit to scale', () => {
    // Nothing multiplied by anything is still nothing, and a page that
    // reported "0%" there would be claiming the case breaks even for free.
    const r = businessCase(of({ oneOffCost: 10_000, monthlyBenefit: 0 }));

    expect(r.breakEvenBenefitPercent).toBeNull();
  });

  it('agrees with the net it is derived from', () => {
    // The claim only holds if scaling the benefit to exactly that fraction
    // lands the case on zero. Anything else and the headline is decorative.
    const input = of({ oneOffCost: 30_000, monthlyCost: 800, monthlyBenefit: 5_000, rampMonths: 4, horizonMonths: 24, discountRatePercent: 8 });
    const r = businessCase(input);
    const scaled = businessCase({ ...input, monthlyBenefit: input.monthlyBenefit * (r.breakEvenBenefitPercent! / 100) });

    expect(scaled.npv).toBeCloseTo(0, 6);
  });
});

describe('the inputs a real form actually receives', () => {
  it('survives an empty field arriving as NaN', () => {
    const r = businessCase(of({ oneOffCost: Number.NaN, monthlyBenefit: Number.NaN }));

    expect(Number.isFinite(r.npv)).toBe(true);
  });

  it('does not divide by zero when nothing has been spent', () => {
    const r = businessCase(of({ monthlyBenefit: 1_000, horizonMonths: 12 }));

    expect(Number.isFinite(r.roiPercent)).toBe(true);
  });

  it('holds the horizon to something a schedule can render', () => {
    const r = businessCase(of({ monthlyBenefit: 1_000, horizonMonths: 5_000 }));

    expect(r.schedule.length).toBeLessThanOrEqual(120);
  });

  it('treats a negative cost as no cost rather than as income', () => {
    const r = businessCase(of({ oneOffCost: -5_000, monthlyBenefit: 1_000, horizonMonths: 12 }));

    expect(r.totalCost).toBe(0);
  });
});
