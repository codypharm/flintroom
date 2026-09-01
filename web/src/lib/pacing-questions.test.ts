import { describe, expect, it } from 'vitest';

import { timeScript } from './pacing';
import { STANDARD_PACING_QUESTIONS, pacingQuestionsFor } from './pacing-questions';

const WORDS = (n: number) => Array.from({ length: n }, (_, i) => `w${i}`).join(' ');

describe('the standard list', () => {
  it('ships at least four, none grounded', () => {
    expect(STANDARD_PACING_QUESTIONS.length).toBeGreaterThanOrEqual(4);
    expect(STANDARD_PACING_QUESTIONS.every((q) => !q.grounded)).toBe(true);
  });
});

describe('grounded questions', () => {
  it('a script over the slot gets asked what it would cut', () => {
    const timed = timeScript({
      script: WORDS(1000),
      paceWpm: 130,
      slotMinutes: 5,
      qaMinutes: 0,
    });

    const asked = pacingQuestionsFor(timed);
    const over = asked.find((q) => q.id === 'over-budget');
    expect(over?.grounded).toBe(true);
    expect(over?.text).toContain('350');
  });

  it('a dense paragraph gets asked where the audience breathes', () => {
    const timed = timeScript({ script: WORDS(200), paceWpm: 130 });

    const asked = pacingQuestionsFor(timed);
    expect(asked.find((q) => q.id === 'dense')?.grounded).toBe(true);
  });

  it('a script that only fits at nervous speed is named as such', () => {
    // 700 words: 5.4 min rehearsed at 130, 4.7 at delivery speed. A 5-minute
    // budget fits only the version of you that is rushing.
    const timed = timeScript({
      script: WORDS(700),
      paceWpm: 130,
      slotMinutes: 5,
      qaMinutes: 0,
    });

    const asked = pacingQuestionsFor(timed);
    expect(asked.find((q) => q.id === 'only-fits-rushed')).toBeUndefined();
    // over-budget already covers it: 700 > 650. The rushed question exists
    // for the inverse — fits the slot, but only after the nerves discount.
    const fits = timeScript({
      script: WORDS(640),
      paceWpm: 130,
      slotMinutes: 5,
      qaMinutes: 0,
    });
    expect(pacingQuestionsFor(fits).find((q) => q.id === 'over-budget')).toBeUndefined();
  });

  it('a fitting, breathable script gets only the standard list', () => {
    const script = [WORDS(80), WORDS(80), WORDS(80)].join('\n\n');
    const timed = timeScript({ script, paceWpm: 130, slotMinutes: 10, qaMinutes: 2 });

    expect(pacingQuestionsFor(timed).every((q) => !q.grounded)).toBe(true);
  });
});
