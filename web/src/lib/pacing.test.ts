import { describe, expect, it } from 'vitest';

import { PACES, timeScript } from './pacing';

const WORDS = (n: number) => Array.from({ length: n }, (_, i) => `word${i}`).join(' ');

describe('counting and timing', () => {
  it('times a script at the chosen pace', () => {
    // 260 words at 130 wpm is exactly two minutes.
    const timed = timeScript({ script: WORDS(260), paceWpm: 130 });

    expect(timed.wordCount).toBe(260);
    expect(timed.minutes).toBeCloseTo(2);
  });

  it('counts words, not whitespace', () => {
    const timed = timeScript({ script: '  one   two\n\nthree  ', paceWpm: 130 });
    expect(timed.wordCount).toBe(3);
  });

  it('an empty script is nothing to time, not zero minutes of speech', () => {
    expect(timeScript({ script: '   ', paceWpm: 130 }).wordCount).toBe(0);
    expect(timeScript({ script: '', paceWpm: 130 }).minutes).toBe(0);
  });
});

describe('the nerves line', () => {
  it('shows the same script delivered 15 percent faster', () => {
    // Under pressure people speed up; 2 minutes rehearsed is about 1.74
    // delivered. The point is the gap, not the precision.
    const timed = timeScript({ script: WORDS(260), paceWpm: 130 });
    expect(timed.nervesMinutes).toBeCloseTo(2 / 1.15);
  });
});

describe('paragraphs on the timeline', () => {
  it('places each paragraph at the minute it starts', () => {
    const script = `${WORDS(130)}\n\n${WORDS(65)}`;
    const timed = timeScript({ script, paceWpm: 130 });

    expect(timed.paragraphs).toHaveLength(2);
    expect(timed.paragraphs[0]!.startMinute).toBe(0);
    expect(timed.paragraphs[1]!.startMinute).toBeCloseTo(1);
    expect(timed.paragraphs[1]!.minutes).toBeCloseTo(0.5);
  });

  it('flags a paragraph that runs past forty-five seconds without a break', () => {
    // Dense is about continuous speech, not word difficulty: a paragraph is
    // where the writing gave the speaker nowhere to breathe, and 45 seconds
    // of unbroken delivery is where audiences report rushing.
    const dense = WORDS(130); // a full minute at 130 wpm
    const brisk = WORDS(60); // under half a minute
    const timed = timeScript({ script: `${dense}\n\n${brisk}`, paceWpm: 130 });

    expect(timed.paragraphs[0]!.dense).toBe(true);
    expect(timed.paragraphs[1]!.dense).toBe(false);
  });
});

describe('the slot budget', () => {
  it('works backwards from the slot to a word budget', () => {
    // A 20-minute slot with 5 minutes of questions is 15 speaking minutes,
    // which at 130 wpm is a 1,950-word budget.
    const timed = timeScript({
      script: WORDS(260),
      paceWpm: 130,
      slotMinutes: 20,
      qaMinutes: 5,
    });

    expect(timed.speakingMinutes).toBe(15);
    expect(timed.wordBudget).toBe(1950);
    expect(timed.wordsOver).toBeNull();
  });

  it('says how many words to cut when the script is over', () => {
    const timed = timeScript({
      script: WORDS(1000),
      paceWpm: 130,
      slotMinutes: 5,
      qaMinutes: 0,
    });

    // 5 minutes at 130 wpm holds 650 words; 1,000 is 350 over.
    expect(timed.wordsOver).toBe(350);
    expect(timed.overMinutes).toBeCloseTo(350 / 130);
  });

  it('a Q&A that eats the whole slot leaves no budget rather than a negative one', () => {
    const timed = timeScript({
      script: WORDS(100),
      paceWpm: 130,
      slotMinutes: 5,
      qaMinutes: 10,
    });

    expect(timed.speakingMinutes).toBe(0);
    expect(timed.wordBudget).toBe(0);
    expect(timed.wordsOver).toBe(100);
  });

  it('no slot means no budget verdict at all', () => {
    const timed = timeScript({ script: WORDS(100), paceWpm: 130 });
    expect(timed.speakingMinutes).toBeNull();
    expect(timed.wordBudget).toBeNull();
    expect(timed.wordsOver).toBeNull();
  });
});

describe('the paces on offer', () => {
  it('ships the two named styles and a deliberate one', () => {
    const names = PACES.map((pace) => pace.wpm);
    expect(names).toContain(130);
    expect(names).toContain(160);
    expect(Math.min(...names)).toBeLessThan(130);
  });
});

describe('saying a duration out loud', () => {
  it('speaks in minutes and seconds, not decimals', async () => {
    const { formatDuration } = await import('./pacing');
    expect(formatDuration(11.5)).toBe('11 min 30 sec');
    expect(formatDuration(0.5)).toBe('30 sec');
    expect(formatDuration(2)).toBe('2 min');
    expect(formatDuration(0)).toBe('0 sec');
  });

  it('never says "60 sec" — carry rounds up the minute', async () => {
    const { formatDuration } = await import('./pacing');
    expect(formatDuration(1.999)).toBe('2 min');
  });
});
