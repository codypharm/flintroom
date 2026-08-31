import { describe, expect, it } from 'vitest';

import { questionsFor, STANDARD_QUESTIONS } from './questions';
import { runway, type RunwayInput } from './runway';

/**
 * What the number invites.
 *
 * This is the half of /tools/runway-calculator that could not have come from
 * anywhere else. Any page can divide cash by burn; the reason to be on ours is
 * that it tells you what gets asked next — which is a small, silent version of
 * what the product does out loud.
 *
 * So the tests here are mostly about tone and honesty rather than arithmetic.
 * The failure mode is not a wrong list, it is a list that grades you.
 */
const JAN = new Date('2026-01-01T00:00:00Z');

function ask(input: Omit<RunwayInput, 'from'>) {
  const from = JAN;
  return questionsFor(runway({ ...input, from }), { ...input, from });
}

/** A comfortable, unremarkable seed: two years of cash, growing modestly. */
const STEADY = { cash: 600_000, monthlySpend: 40_000, monthlyRevenue: 15_000, burnGrowthPercent: 3, revenueGrowthPercent: 6 };

describe('the shape of every question', () => {
  it('asks rather than concludes', () => {
    // The product rule, and the one that matters most here: Flintroom never
    // returns a verdict. A line that told a founder their burn was too high
    // would be a scorecard, and the whole positioning is that we are not one.
    for (const question of ask(STEADY)) {
      expect(question.text.trim().endsWith('?')).toBe(true);
    }
  });

  it('never grades the answer', () => {
    const graded = /\b(too (high|low|slow|fast)|should be|you need to|bad|wrong|unrealistic)\b/i;

    for (const question of ask(STEADY)) {
      expect(question.text).not.toMatch(graded);
      expect(question.why).not.toMatch(graded);
    }
  });

  it('says who asks it and why, because not everybody has been in the room', () => {
    // The page serves somebody who has done ten of these and somebody who has
    // done none. The question alone serves the first; `why` is what the second
    // one needs, and it costs the first a second to skip.
    for (const question of ask(STEADY)) {
      expect(question.why.length).toBeGreaterThan(20);
    }
  });

  it('stays short enough to be read standing up', () => {
    for (const question of ask(STEADY)) {
      expect(question.text.length).toBeLessThan(140);
    }
  });
});

describe('the questions every runway number invites', () => {
  it('asks gross or net whatever the inputs say', () => {
    const universal = ask(STEADY).map((q) => q.text.toLowerCase());

    expect(universal.some((t) => t.includes('gross'))).toBe(true);
  });

  it('is never empty, even on inputs nobody filled in', () => {
    const bare = ask({ cash: 0, monthlySpend: 0, monthlyRevenue: 0, burnGrowthPercent: 0 });

    expect(bare.length).toBeGreaterThan(0);
  });
});

describe('the questions your own numbers invite', () => {
  it('notices when burn has been left flat', () => {
    const flat = ask({ ...STEADY, burnGrowthPercent: 0 });
    const growing = ask({ ...STEADY, burnGrowthPercent: 5 });

    expect(flat.some((q) => q.id === 'flat-burn')).toBe(true);
    expect(growing.some((q) => q.id === 'flat-burn')).toBe(false);
  });

  it('notices when there is no revenue in the model', () => {
    const none = ask({ ...STEADY, monthlyRevenue: 0 });

    expect(none.some((q) => q.id === 'no-revenue')).toBe(true);
  });

  it('asks a default-dead company how it intends to stop being one', () => {
    // 3% growth cannot close a 2x gap in four months of cash.
    const dead = ask({ cash: 40_000, monthlySpend: 20_000, monthlyRevenue: 10_000, burnGrowthPercent: 0, revenueGrowthPercent: 3 });

    expect(dead.some((q) => q.id === 'default-dead')).toBe(true);
    expect(dead.some((q) => q.id === 'default-alive')).toBe(false);
  });

  it('asks a default-alive company which line it is least sure of', () => {
    const alive = ask({ cash: 300_000, monthlySpend: 20_000, monthlyRevenue: 10_000, burnGrowthPercent: 0, revenueGrowthPercent: 15 });

    expect(alive.some((q) => q.id === 'default-alive')).toBe(true);
    expect(alive.some((q) => q.id === 'default-dead')).toBe(false);
  });

  it('treats under six months as a raise already in progress', () => {
    const short = ask({ cash: 60_000, monthlySpend: 20_000, monthlyRevenue: 0, burnGrowthPercent: 0 });

    expect(short.some((q) => q.id === 'short-runway')).toBe(true);
  });

  it('asks a long runway for the milestone rather than the date', () => {
    const long = ask({ cash: 2_000_000, monthlySpend: 40_000, monthlyRevenue: 0, burnGrowthPercent: 0 });

    expect(long.some((q) => q.id === 'long-runway')).toBe(true);
    expect(long.some((q) => q.id === 'short-runway')).toBe(false);
  });

  it('does not ask both the short and the long question at once', () => {
    for (const months of [3, 12, 30]) {
      const list = ask({ cash: months * 10_000, monthlySpend: 10_000, monthlyRevenue: 0, burnGrowthPercent: 0 });
      const both = list.some((q) => q.id === 'short-runway') && list.some((q) => q.id === 'long-runway');

      expect(both).toBe(false);
    }
  });
});

describe('how many arrive at once', () => {
  it('stops well short of a wall of text', () => {
    // Every conditional firing at the same time is a real input, not a
    // hypothetical: no revenue, flat burn, and barely any cash is what a
    // pre-seed founder types. Seven hard questions is a page you read; twelve
    // is a page you close.
    const everything = ask({ cash: 20_000, monthlySpend: 20_000, monthlyRevenue: 0, burnGrowthPercent: 0 });

    expect(everything.length).toBeLessThanOrEqual(7);
  });

  it('leads with the ones drawn from what they actually typed', () => {
    // A generic question first reads as a listicle. A question about their own
    // number first reads as having been listened to, which is the entire
    // impression this page exists to leave.
    const list = ask({ ...STEADY, monthlyRevenue: 0 });

    expect(list[0].grounded).toBe(true);
  });

  it('returns no duplicates', () => {
    const ids = ask({ cash: 20_000, monthlySpend: 20_000, monthlyRevenue: 0, burnGrowthPercent: 0 }).map((q) => q.id);

    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe('the empty page', () => {
  it('has something honest to show before anything is typed', () => {
    // The fields start empty on purpose, so there is nothing to ground a
    // question in yet. These four are asked of every runway number ever
    // quoted, which is what makes them safe to show to a blank form.
    expect(STANDARD_QUESTIONS.length).toBeGreaterThan(2);

    for (const question of STANDARD_QUESTIONS) {
      expect(question.grounded).toBe(false);
      expect(question.text.trim().endsWith('?')).toBe(true);
    }
  });
});
