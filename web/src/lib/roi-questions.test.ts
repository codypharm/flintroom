import { describe, expect, it } from 'vitest';

import { businessCase, type RoiInput } from './roi';
import { roiQuestionsFor, STANDARD_ROI_QUESTIONS } from './roi-questions';

/** What gets asked across the table, and the tone it has to be asked in. */
function ask(over: Partial<RoiInput> = {}) {
  const input: RoiInput = {
    oneOffCost: 24_000, monthlyCost: 500, monthlyBenefit: 4_000,
    rampMonths: 3, horizonMonths: 36, discountRatePercent: 10, ...over,
  };
  return roiQuestionsFor(businessCase(input), input);
}

describe('the shape of every question', () => {
  it('asks rather than concludes', () => {
    for (const q of ask()) expect(q.text.trim().endsWith('?')).toBe(true);
  });

  it('never grades the case', () => {
    const graded = /\b(too (high|low|small|big)|weak|poor|should be|you need to|bad|unrealistic)\b/i;

    for (const over of [{}, { rampMonths: 0 }, { monthlyBenefit: 200 }, { monthlyCost: 0 }]) {
      for (const q of ask(over)) {
        expect(q.text).not.toMatch(graded);
        expect(q.why).not.toMatch(graded);
      }
    }
  });

  it('explains who asks it and why', () => {
    for (const q of ask()) expect(q.why.length).toBeGreaterThan(20);
  });
});

describe('the questions a case invites', () => {
  it('asks a case that never pays back for its non-financial argument', () => {
    const list = ask({ oneOffCost: 500_000, monthlyBenefit: 1_000 });

    expect(list.some((q) => q.id === 'never-pays')).toBe(true);
    expect(list.some((q) => q.id === 'fragile')).toBe(false);
  });

  it('asks a fragile case what sixty percent looks like', () => {
    // Break-even lands near 87%: enough room to pay back, not enough to
    // survive the forecast arriving short. At 118,000 it tips past 100 and
    // correctly becomes the other question — the band is narrow on purpose.
    const list = ask({ oneOffCost: 90_000, monthlyBenefit: 4_000, horizonMonths: 36 });

    expect(list.some((q) => q.id === 'fragile')).toBe(true);
  });

  it('asks a very comfortable case what is missing', () => {
    // A margin this wide usually means a cost line is absent rather than that
    // the case is unusually good.
    const list = ask({ oneOffCost: 5_000, monthlyCost: 0, monthlyBenefit: 4_000 });

    expect(list.some((q) => q.id === 'too-good')).toBe(true);
  });

  it('raises exactly one of the three break-even questions', () => {
    for (const over of [{}, { oneOffCost: 500_000 }, { oneOffCost: 1_000, monthlyCost: 0 }]) {
      const ids = ask(over).map((q) => q.id);
      const hits = ['never-pays', 'fragile', 'too-good'].filter((id) => ids.includes(id));

      expect(hits.length).toBeLessThanOrEqual(1);
    }
  });

  it('notices a case with no ramp in it', () => {
    expect(ask({ rampMonths: 0 }).some((q) => q.id === 'no-ramp')).toBe(true);
    expect(ask({ rampMonths: 3 }).some((q) => q.id === 'no-ramp')).toBe(false);
  });

  it('notices a case with no running cost in it', () => {
    expect(ask({ monthlyCost: 0 }).some((q) => q.id === 'no-running-cost')).toBe(true);
  });

  it('notices a horizon longer than a committee expects', () => {
    expect(ask({ horizonMonths: 60 }).some((q) => q.id === 'long-horizon')).toBe(true);
    expect(ask({ horizonMonths: 36 }).some((q) => q.id === 'long-horizon')).toBe(false);
  });

  it('asks about payback landing past the next planning cycle', () => {
    const list = ask({ oneOffCost: 110_000, monthlyBenefit: 4_000, horizonMonths: 60 });

    expect(list.some((q) => q.id === 'slow-payback')).toBe(true);
  });
});

describe('how many arrive at once', () => {
  it('stops short of a wall of text', () => {
    const everything = ask({ oneOffCost: 400_000, monthlyCost: 0, monthlyBenefit: 4_000, rampMonths: 0, horizonMonths: 60 });

    expect(everything.length).toBeLessThanOrEqual(7);
  });

  it('leads with the ones drawn from their own case', () => {
    expect(ask({ rampMonths: 0 })[0].grounded).toBe(true);
  });

  it('has something honest to show a blank form', () => {
    expect(STANDARD_ROI_QUESTIONS.length).toBeGreaterThan(2);
    for (const q of STANDARD_ROI_QUESTIONS) {
      expect(q.grounded).toBe(false);
      expect(q.text.trim().endsWith('?')).toBe(true);
    }
  });

  it('returns no duplicates', () => {
    const ids = ask({ oneOffCost: 400_000, monthlyCost: 0, rampMonths: 0, horizonMonths: 60 }).map((q) => q.id);

    expect(new Set(ids).size).toBe(ids.length);
  });
});
