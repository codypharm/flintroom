import { describe, expect, it } from 'vitest';

import { priceChange, type PriceChangeInput } from './pricing';

/**
 * The arithmetic behind /tools/price-change-calculator.
 *
 * One number carries the page: how much volume a price change can afford to
 * lose, or has to gain. It is genuinely surprising in both directions and it
 * is almost never computed before the decision is made — which is the whole
 * reason to build it.
 */
function of(over: Partial<PriceChangeInput> = {}): PriceChangeInput {
  return { price: 100, grossMarginPercent: 30, changePercent: 10, monthlyVolume: 0, ...over };
}

describe('raising the price', () => {
  it('says how much volume can go before the change stops paying', () => {
    // 100 at 30% margin is 30 of contribution. At 110 it is 40. The same total
    // contribution now needs 30/40 of the customers — so a quarter of them can
    // leave and the business is exactly where it was.
    const r = priceChange(of({ changePercent: 10 }));

    expect(r.volumeChangeNeededPercent).toBeCloseTo(-25, 6);
    expect(r.raising).toBe(true);
  });

  it('can afford to lose more when the margin is thinner', () => {
    // The counterintuitive half, and the reason the page exists. A thin margin
    // means the price rise is a huge proportional gain on contribution, so it
    // tolerates far more attrition — not less.
    const thin = priceChange(of({ grossMarginPercent: 10, changePercent: 10 }));
    const fat = priceChange(of({ grossMarginPercent: 60, changePercent: 10 }));

    expect(Math.abs(thin.volumeChangeNeededPercent!)).toBeGreaterThan(
      Math.abs(fat.volumeChangeNeededPercent!),
    );
  });

  it('turns the share into a count when volume is known', () => {
    const r = priceChange(of({ changePercent: 10, monthlyVolume: 400 }));

    expect(r.customersAtStake).toBeCloseTo(100, 6);
  });

  it('leaves the count out when nobody said how many there are', () => {
    expect(priceChange(of({ monthlyVolume: 0 })).customersAtStake).toBeNull();
  });
});

describe('cutting the price', () => {
  it('says how much more volume the discount demands', () => {
    // 100 at 30% margin discounted 10%: contribution falls from 30 to 20, so
    // it takes half again as many customers to stand still. This is the number
    // that stops a meeting.
    const r = priceChange(of({ changePercent: -10 }));

    expect(r.volumeChangeNeededPercent).toBeCloseTo(50, 6);
    expect(r.raising).toBe(false);
  });

  it('demands more the thinner the margin', () => {
    const thin = priceChange(of({ grossMarginPercent: 15, changePercent: -10 }));
    const fat = priceChange(of({ grossMarginPercent: 60, changePercent: -10 }));

    expect(thin.volumeChangeNeededPercent!).toBeGreaterThan(fat.volumeChangeNeededPercent!);
  });

  it('has no answer when the discount is larger than the margin', () => {
    // Cutting 40% off a 30% margin sells every unit below cost. No amount of
    // volume fixes that, and reporting a very large percentage would imply one
    // exists.
    const r = priceChange(of({ grossMarginPercent: 30, changePercent: -40 }));

    expect(r.volumeChangeNeededPercent).toBeNull();
    expect(r.belowCost).toBe(true);
  });

  it('treats a discount exactly equal to the margin as selling at cost', () => {
    const r = priceChange(of({ grossMarginPercent: 30, changePercent: -30 }));

    expect(r.volumeChangeNeededPercent).toBeNull();
    expect(r.belowCost).toBe(true);
  });
});

describe('the contribution either side of the change', () => {
  it('reports what one sale earns before and after', () => {
    const r = priceChange(of({ price: 100, grossMarginPercent: 30, changePercent: 10 }));

    expect(r.contributionBefore).toBeCloseTo(30, 6);
    expect(r.contributionAfter).toBeCloseTo(40, 6);
    expect(r.newPrice).toBeCloseTo(110, 6);
  });

  it('holds the unit cost still, because a price change does not move it', () => {
    // The cost of the thing is what it is; only the price and therefore the
    // margin move. Recomputing cost from the new price is the classic error
    // and it makes every price rise look free.
    const r = priceChange(of({ price: 200, grossMarginPercent: 25, changePercent: 20 }));

    expect(r.unitCost).toBeCloseTo(150, 6);
    expect(r.contributionAfter).toBeCloseTo(240 - 150, 6);
  });
});

describe('the inputs a real form actually receives', () => {
  it('has nothing to say about a change of nothing', () => {
    const r = priceChange(of({ changePercent: 0 }));

    expect(r.volumeChangeNeededPercent).toBe(0);
  });

  it('survives an empty field arriving as NaN', () => {
    const r = priceChange(of({ price: Number.NaN, grossMarginPercent: Number.NaN }));

    expect(Number.isFinite(r.contributionBefore)).toBe(true);
  });

  it('has no answer without a margin, because contribution would be zero', () => {
    const r = priceChange(of({ grossMarginPercent: 0 }));

    expect(r.volumeChangeNeededPercent).toBeNull();
  });

  it('holds margin to a hundred', () => {
    const r = priceChange(of({ grossMarginPercent: 250 }));

    expect(r.unitCost).toBe(0);
  });

  it('refuses to price below free', () => {
    const r = priceChange(of({ changePercent: -400 }));

    expect(r.newPrice).toBeGreaterThanOrEqual(0);
  });
});
