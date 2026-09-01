import type { TimedScript } from './pacing';
import type { Question } from './question';

/**
 * What gets asked about a timing.
 *
 * Not by the audience — by the organiser with a schedule, the chair with a
 * hard stop, and the speaker themselves at the lectern discovering the clock.
 * A script that "takes 12 minutes" is an estimate made in silence; every
 * question here is about the ways a room disagrees with an estimate.
 */

export const STANDARD_PACING_QUESTIONS: Question[] = [
  {
    id: 'reading-is-not-speaking',
    text: 'Have you said this out loud yet, or only read it?',
    why: 'Reading silently runs two to three times faster than speech, so a script that "reads fine" is usually long. The number on this page assumes delivery pace — the only way to know your actual pace is to say it and time it.',
    grounded: false,
  },
  {
    id: 'slides-and-silence',
    text: 'What happens on stage that is not in the script?',
    why: 'Slide changes, the demo loading, the laugh you wait out, drinking water. None of it is words, all of it is minutes, and a script timed to exactly fill the slot has budgeted zero for any of it.',
    grounded: false,
  },
  {
    id: 'the-speaker-before-you',
    text: 'What is the plan when the speaker before you runs over?',
    why: 'Slots shrink from the front. The version of this talk that fits in two-thirds of the time is a decision to make now, calmly — the one made live on stage is always "talk faster", which loses the room.',
    grounded: false,
  },
  {
    id: 'ending-early',
    text: 'What would you do with two spare minutes?',
    why: 'Finishing early reads as command of the material; finishing exactly on time reads as luck. A script cut to ninety percent of the speaking time leaves room for the audience to exist.',
    grounded: false,
  },
];

/**
 * Fits only when rushed: rehearsed pace runs over, delivery pace squeaks in.
 * The trap case, because practising it feels fine right up until the day.
 */
function fitsOnlyRushed(timed: TimedScript): boolean {
  return (
    timed.speakingMinutes !== null &&
    timed.wordsOver === null &&
    timed.minutes > timed.speakingMinutes &&
    timed.nervesMinutes <= timed.speakingMinutes
  );
}

export function pacingQuestionsFor(timed: TimedScript): Question[] {
  const grounded: Question[] = [];

  if (timed.wordsOver !== null) {
    grounded.push({
      id: 'over-budget',
      text: `You are about ${timed.wordsOver} words past what the slot holds. Which section gives them up?`,
      why: 'Cuts made at the desk come out of the weakest section; cuts made on stage come out of whatever was last — usually the ask, the summary, the reason you were speaking at all. Nobody cuts evenly under pressure, so the decision is better made here.',
      grounded: true,
    });
  } else if (fitsOnlyRushed(timed)) {
    grounded.push({
      id: 'only-fits-rushed',
      text: 'This only fits at the pace you talk when nervous. Is that the plan?',
      why: 'At your rehearsed pace it runs over; it fits only with the speed that nerves add. Speed that comes from nerves is not pacing, it is rushing — and it spends exactly the sections that needed the room to follow.',
      grounded: true,
    });
  }

  if (timed.paragraphs.some((paragraph) => paragraph.dense)) {
    grounded.push({
      id: 'dense',
      text: 'There are stretches here past forty-five seconds with nowhere to breathe. Where does the audience catch up?',
      why: 'A paragraph is where the writing gives the speaker a break. A long one delivered at pace is where rushing happens and where listeners fall behind — the fix is a break in the text, not effort on the day.',
      grounded: true,
    });
  }

  return [...grounded, ...STANDARD_PACING_QUESTIONS];
}
