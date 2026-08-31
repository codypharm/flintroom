import { describe, expect, it } from 'vitest';

import { priceChange, type PriceChangeInput } from './pricing';
import { pricingQuestionsFor, STANDARD_PRICING_QUESTIONS } from './pricing-questions';

function ask(over: Partial<PriceChangeInput> = {}) {
  const input: PriceChangeInput = {
    price: 100, grossMarginPercent: 30, changePercent: 10, monthlyVolume: 0, ...over,
  };
  return pricingQuestionsFor(priceChange(input), input);
}

describe('the shape of every question', () => {
  it('asks rather than concludes', () => {
    for (const q of ask()) expect(q.text.trim().endsWith('?')).toBe(true);
  });

  it('never grades the decision', () => {
    const graded = /\b(too (high|low|big|small|cheap|expensive)|should be|you need to|bad|wrong|unwise|risky move)\b/i;

    for (const over of [{}, { changePercent: -10 }, { changePercent: -50 }, { grossMarginPercent: 10 }, { changePercent: 40 }]) {
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

describe('the questions a change invites', () => {
  it('puts the demanded volume in the discount question', () => {
    // "This needs 50% more volume." The number is the argument.
    const list = ask({ changePercent: -10 });
    const found = list.find((q) => q.id === 'discount-demand');

    expect(found).toBeDefined();
    expect(found!.text).toContain('50%');
  });

  it('asks a below-cost discount for its non-volume argument', () => {
    const list = ask({ changePercent: -50 });

    expect(list.some((q) => q.id === 'below-cost')).toBe(true);
    expect(list.some((q) => q.id === 'discount-demand')).toBe(false);
  });

  it('asks a comfortable rise which customers go first', () => {
    const list = ask({ changePercent: 10 });

    expect(list.some((q) => q.id === 'wide-tolerance')).toBe(true);
  });

  it('does not ask that of a rise with little room in it', () => {
    // A 2% rise at a fat margin tolerates very little attrition.
    const list = ask({ grossMarginPercent: 80, changePercent: 2 });

    expect(list.some((q) => q.id === 'wide-tolerance')).toBe(false);
  });

  it('treats a large move as a repositioning', () => {
    expect(ask({ changePercent: 40 }).some((q) => q.id === 'repositioning')).toBe(true);
    expect(ask({ changePercent: 10 }).some((q) => q.id === 'repositioning')).toBe(false);
  });

  it('asks a thin margin what happens when costs move', () => {
    expect(ask({ grossMarginPercent: 10 }).some((q) => q.id === 'thin-margin')).toBe(true);
  });

  it('asks for ten names once it can count the customers', () => {
    const list = ask({ monthlyVolume: 400 });
    const found = list.find((q) => q.id === 'named-customers');

    expect(found).toBeDefined();
    expect(found!.text).toContain('100');
  });

  it('says nothing about counts when nobody gave a volume', () => {
    expect(ask({ monthlyVolume: 0 }).some((q) => q.id === 'named-customers')).toBe(false);
  });
});

describe('how many arrive at once', () => {
  it('stops short of a wall of text', () => {
    const everything = ask({ changePercent: -35, grossMarginPercent: 10, monthlyVolume: 900 });

    expect(everything.length).toBeLessThanOrEqual(7);
  });

  it('leads with the ones drawn from their own numbers', () => {
    expect(ask()[0].grounded).toBe(true);
  });

  it('has something honest to show a blank form', () => {
    expect(STANDARD_PRICING_QUESTIONS.length).toBeGreaterThan(2);
    for (const q of STANDARD_PRICING_QUESTIONS) {
      expect(q.grounded).toBe(false);
      expect(q.text.trim().endsWith('?')).toBe(true);
    }
  });

  it('returns no duplicates', () => {
    const ids = ask({ changePercent: -35, grossMarginPercent: 10, monthlyVolume: 900 }).map((q) => q.id);

    expect(new Set(ids).size).toBe(ids.length);
  });
});
