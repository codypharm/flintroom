import { describe, expect, it } from 'vitest';

import { breakEven, type BreakEvenInput } from './break-even';
import { breakEvenQuestionsFor, STANDARD_BREAK_EVEN_QUESTIONS } from './break-even-questions';

function ask(over: Partial<BreakEvenInput> = {}) {
  const input: BreakEvenInput = {
    monthlyFixedCosts: 12_000, price: 100, grossMarginPercent: 40, monthlyVolume: 500, ...over,
  };
  return breakEvenQuestionsFor(breakEven(input), input);
}

describe('the shape of every question', () => {
  it('asks rather than concludes', () => {
    for (const q of ask()) expect(q.text.trim().endsWith('?')).toBe(true);
  });

  it('never grades the business', () => {
    const graded = /\b(too (high|low|thin|small)|should be|you need to|bad|wrong|unsustainable|failing)\b/i;

    for (const over of [{}, { monthlyFixedCosts: 24_000 }, { grossMarginPercent: 0 }, { monthlyVolume: 0 }, { monthlyFixedCosts: 2_000 }]) {
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

describe('the questions the figures invite', () => {
  it('counts the sales a short month is missing', () => {
    const found = ask({ monthlyFixedCosts: 24_000 }).find((q) => q.id === 'short');

    expect(found).toBeDefined();
    expect(found!.text).toContain('100');
  });

  it('asks whether a missing margin is missing or real', () => {
    expect(ask({ grossMarginPercent: 0 }).some((q) => q.id === 'no-contribution')).toBe(true);
  });

  it('asks what a bad month looks like when the room is thin', () => {
    // Break-even at 450 of 500 sales: a tenth of the volume is the whole gap.
    expect(ask({ monthlyFixedCosts: 18_000 }).some((q) => q.id === 'thin-safety')).toBe(true);
    expect(ask().some((q) => q.id === 'thin-safety')).toBe(false);
  });

  it('asks which cost goes first when the month is nearly spent', () => {
    const list = ask({ monthlyFixedCosts: 19_600 });

    expect(list.some((q) => q.id === 'late-day')).toBe(true);
  });

  it('asks an early break-even why it is not spending more', () => {
    const list = ask({ monthlyFixedCosts: 2_000 });

    expect(list.some((q) => q.id === 'early-day')).toBe(true);
    expect(list.some((q) => q.id === 'late-day')).toBe(false);
  });

  it('asks for the volume when nobody gave one', () => {
    expect(ask({ monthlyVolume: 0 }).some((q) => q.id === 'no-volume')).toBe(true);
    expect(ask().some((q) => q.id === 'no-volume')).toBe(false);
  });
});

describe('how many arrive at once', () => {
  it('stops short of a wall of text', () => {
    const everything = ask({ monthlyFixedCosts: 24_000, grossMarginPercent: 0, monthlyVolume: 0 });

    expect(everything.length).toBeLessThanOrEqual(7);
  });

  it('leads with the ones drawn from their own figures', () => {
    expect(ask({ monthlyFixedCosts: 24_000 })[0].grounded).toBe(true);
  });

  it('has something honest to show a blank form', () => {
    expect(STANDARD_BREAK_EVEN_QUESTIONS.length).toBeGreaterThan(2);
    for (const q of STANDARD_BREAK_EVEN_QUESTIONS) {
      expect(q.grounded).toBe(false);
      expect(q.text.trim().endsWith('?')).toBe(true);
    }
  });

  it('returns no duplicates', () => {
    const ids = ask({ monthlyFixedCosts: 24_000, monthlyVolume: 0 }).map((q) => q.id);

    expect(new Set(ids).size).toBe(ids.length);
  });
});
