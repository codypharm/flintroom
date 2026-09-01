/**
 * How long a script actually takes to say — and what fits the slot.
 *
 * The standard version of this tool is words divided by 130, which answers a
 * question nobody is really asking. The questions people run over on are the
 * other way round: *I have twenty minutes — what fits?* So beside the timing
 * this works backwards from the slot: slot minus Q&A is the speaking time,
 * speaking time at your pace is a word budget, and the distance between the
 * budget and the script is the sentence to act on — "cut about 350 words".
 *
 * Everything here is arithmetic on the client. The script never leaves the
 * browser; there is no request to make.
 */

/** A speaking style, as a pace. The names are the page's; the numbers rule. */
export interface Pace {
  wpm: number;
  name: string;
  hint: string;
}

/**
 * Three, deliberately few. Published speaking-rate ranges put conversational
 * English near 120–150 wpm; 130 is the convention every competitor uses and
 * matching it keeps our total comparable to what people expect. 160 is a
 * pitch under time pressure. 110 is what a keynote or a board readout should
 * actually run at — the pace nobody budgets for.
 */
export const PACES: readonly Pace[] = [
  { wpm: 110, name: 'Deliberate', hint: 'Keynotes, board readouts, anything with numbers' },
  { wpm: 130, name: 'Conversational', hint: 'Most presentations land here' },
  { wpm: 160, name: 'Fast pitch', hint: 'Demo day. Hard to follow for long' },
];

/**
 * Under pressure people speed up, not down. Fifteen percent is a round,
 * defensible middle of the reported range — enough to matter over ten
 * minutes, not so much it reads as a scare figure.
 */
const NERVES = 1.15;

/**
 * Forty-five seconds of continuous speech with nowhere to breathe. Density is
 * about the *writing* — a paragraph is where the author gave the speaker a
 * break, so a long one at pace is where rushing happens — which is why the
 * threshold is time at the chosen pace rather than a word count.
 */
const DENSE_MINUTES = 0.75;

export interface PacingInput {
  script: string;
  paceWpm: number;
  /** The whole booking. Optional; without it there is no budget verdict. */
  slotMinutes?: number;
  /** Questions, intros, the speaker before you running over. */
  qaMinutes?: number;
}

export interface TimedParagraph {
  words: number;
  minutes: number;
  /** Where on the timeline it begins, in minutes from the top. */
  startMinute: number;
  /** Runs past 45 seconds without a break — where rushing happens. */
  dense: boolean;
}

export interface TimedScript {
  wordCount: number;
  /** At the chosen pace. */
  minutes: number;
  /** The same script delivered at nervous speed. Always shorter. */
  nervesMinutes: number;
  paragraphs: TimedParagraph[];
  /** Slot minus Q&A, floored at zero. Null when no slot was given. */
  speakingMinutes: number | null;
  /** Words that fit the speaking minutes at this pace. */
  wordBudget: number | null;
  /** Words past the budget, or null when it fits (or there is no budget). */
  wordsOver: number | null;
  /** The same overrun as time at the chosen pace. */
  overMinutes: number | null;
}

function words(text: string): number {
  const found = text.trim().match(/\S+/g);
  return found ? found.length : 0;
}

export function timeScript(input: PacingInput): TimedScript {
  const wpm = Math.max(1, Number.isFinite(input.paceWpm) ? input.paceWpm : 130);

  // Blank lines are the paragraph breaks a script actually has; a wall of
  // single-newline speaker notes still lands as one paragraph, which then
  // honestly reads as dense — it is.
  const blocks = input.script
    .split(/\n\s*\n/)
    .map((block) => words(block))
    .filter((count) => count > 0);

  const wordCount = blocks.reduce((sum, count) => sum + count, 0);
  const minutes = wordCount / wpm;

  let start = 0;
  const paragraphs: TimedParagraph[] = blocks.map((count) => {
    const length = count / wpm;
    const placed = {
      words: count,
      minutes: length,
      startMinute: start,
      dense: length > DENSE_MINUTES,
    };
    start += length;
    return placed;
  });

  const slot = input.slotMinutes;
  const hasSlot = slot !== undefined && Number.isFinite(slot) && slot > 0;
  const qa = Math.max(0, input.qaMinutes ?? 0);
  const speakingMinutes = hasSlot ? Math.max(0, slot - qa) : null;
  const wordBudget = speakingMinutes === null ? null : Math.floor(speakingMinutes * wpm);
  const over = wordBudget === null ? null : wordCount - wordBudget;
  const wordsOver = over !== null && over > 0 ? over : null;

  return {
    wordCount,
    minutes,
    nervesMinutes: minutes / NERVES,
    paragraphs,
    speakingMinutes,
    wordBudget,
    wordsOver,
    overMinutes: wordsOver === null ? null : wordsOver / wpm,
  };
}

/**
 * A duration the way a speaker says one: "11 min 30 sec", never "11.5".
 * Seconds are rounded to the nearest — a timing tool that pretends to
 * second-level precision about human speech would be lying anyway.
 */
export function formatDuration(minutes: number): string {
  const whole = Math.floor(minutes);
  const seconds = Math.round((minutes - whole) * 60);
  const carriedMinutes = seconds === 60 ? whole + 1 : whole;
  const carriedSeconds = seconds === 60 ? 0 : seconds;

  if (carriedMinutes === 0) return `${carriedSeconds} sec`;
  if (carriedSeconds === 0) return `${carriedMinutes} min`;
  return `${carriedMinutes} min ${carriedSeconds} sec`;
}
