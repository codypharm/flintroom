import { describe, expect, it } from 'vitest';

import { unitEconomics, type UnitEconomicsInput } from './unit-economics';
import { STANDARD_UNIT_QUESTIONS, unitQuestionsFor } from './unit-economics-questions';

function ask(over: Partial<UnitEconomicsInput> = {}) {
  const input: UnitEconomicsInput = {
    monthlyRevenuePerCustomer: 100, grossMarginPercent: 70,
    monthlyChurnPercent: 3, cac: 500, monthsOperating: 14, ...over,
  };
  return unitQuestionsFor(unitEconomics(input), input);
}

describe('the shape of every question', () => {
  it('asks rather than concludes', () => {
    for (const q of ask()) expect(q.text.trim().endsWith('?')).toBe(true);
  });

  it('never grades the numbers', () => {
    const graded = /\b(too (high|low|small|big|expensive)|weak|poor|should be|you need to|bad|unrealistic)\b/i;

    for (const over of [{}, { cac: 0 }, { monthlyChurnPercent: 0 }, { grossMarginPercent: 20 }, { cac: 5_000 }]) {
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

describe('the question the page exists for', () => {
  it('names both durations, because the specificity is the point', () => {
    // "This assumes 33 months. You have been operating 14." Without the two
    // figures it is a lecture rather than an observation about their slide.
    const [first] = ask({ monthlyChurnPercent: 3, monthsOperating: 14 });

    expect(first.id).toBe('lifetime-vs-history');
    expect(first.text).toContain('33');
    expect(first.text).toContain('14');
  });

  it('stays quiet when the company has outlived its own assumption', () => {
    expect(ask({ monthsOperating: 60 }).some((q) => q.id === 'lifetime-vs-history')).toBe(false);
  });
});

describe('the questions their own numbers invite', () => {
  it('treats zero churn as a missing input rather than a result', () => {
    const list = ask({ monthlyChurnPercent: 0 });

    expect(list.some((q) => q.id === 'no-churn')).toBe(true);
    expect(list.some((q) => q.id === 'lifetime-vs-history')).toBe(false);
  });

  it('asks a very comfortable ratio why it is not spending more', () => {
    // The investor's reading of a high ratio: money left on the table.
    const list = ask({ cac: 200 });

    expect(list.some((q) => q.id === 'too-efficient')).toBe(true);
  });

  it('asks a thin ratio which lever moves', () => {
    const list = ask({ cac: 2_000 });

    expect(list.some((q) => q.id === 'thin-ratio')).toBe(true);
  });

  it('never asks both ratio questions at once', () => {
    for (const cac of [200, 800, 2_000]) {
      const ids = ask({ cac }).map((q) => q.id);
      const both = ids.includes('too-efficient') && ids.includes('thin-ratio');

      expect(both).toBe(false);
    }
  });

  it('asks what funds a payback longer than a year', () => {
    const list = ask({ cac: 2_000 });

    expect(list.some((q) => q.id === 'slow-payback')).toBe(true);
    expect(list.find((q) => q.id === 'slow-payback')!.text).toMatch(/\d+ months/);
  });

  it('asks whether a thin margin is structural', () => {
    expect(ask({ grossMarginPercent: 20 }).some((q) => q.id === 'thin-margin')).toBe(true);
    expect(ask({ grossMarginPercent: 70 }).some((q) => q.id === 'thin-margin')).toBe(false);
  });

  it('asks whose time is uncounted when growth looks free', () => {
    expect(ask({ cac: 0 }).some((q) => q.id === 'free-growth')).toBe(true);
  });
});

describe('how many arrive at once', () => {
  it('stops short of a wall of text', () => {
    const everything = ask({ cac: 0, grossMarginPercent: 20, monthlyChurnPercent: 0, monthsOperating: 3 });

    expect(everything.length).toBeLessThanOrEqual(7);
  });

  it('leads with the ones drawn from their own figures', () => {
    expect(ask()[0].grounded).toBe(true);
  });

  it('has something honest to show a blank form', () => {
    expect(STANDARD_UNIT_QUESTIONS.length).toBeGreaterThan(2);
    for (const q of STANDARD_UNIT_QUESTIONS) {
      expect(q.grounded).toBe(false);
      expect(q.text.trim().endsWith('?')).toBe(true);
    }
  });

  it('returns no duplicates', () => {
    const ids = ask({ cac: 0, grossMarginPercent: 20, monthlyChurnPercent: 0 }).map((q) => q.id);

    expect(new Set(ids).size).toBe(ids.length);
  });
});
