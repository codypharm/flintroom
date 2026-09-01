import type { Question } from './question';
import type { UnitEconomics, UnitEconomicsInput } from './unit-economics';

/**
 * What gets asked about a unit-economics slide.
 *
 * The runway page's framing rather than the dilution page's: this number is
 * defended across a table, not negotiated. And almost every question here is
 * really the same question — *how do you know?* — because the ratio is built
 * out of two estimates and a forecast.
 *
 * Nothing grades the figures. "Your CAC is too high" is a verdict, and the
 * product does not return verdicts.
 */

const MOST = 7;

/** Below this the model itself starts getting questioned rather than the inputs. */
const THIN_RATIO = 3;

/** Above this, the question stops being efficiency and becomes underinvestment. */
const SUSPICIOUS_RATIO = 5;

/** Past a year, the gap has to be funded by something. */
const SLOW_PAYBACK = 12;

/** Below this, most of the revenue is cost of sale. */
const THIN_MARGIN = 50;

/** Asked of every unit-economics slide ever put up. */
export const STANDARD_UNIT_QUESTIONS: Question[] = [
  {
    id: 'cac-contents',
    text: 'What is inside CAC: only the ad spend, or the salaries of the people doing the acquiring?',
    why: 'Fully loaded CAC includes sales and marketing headcount, tooling and commissions. Ad-spend-only CAC is a smaller and more flattering number, and the difference between the two is usually where a disagreement about this slide actually lives.',
    grounded: false,
  },
  {
    id: 'blended',
    text: 'Is this blended across channels, or is it one channel?',
    why: 'A blended figure averages the channel that works with the one that does not, and the average is not what you would scale. The follow-up is always the worst channel rather than the mean.',
    grounded: false,
  },
  {
    id: 'expansion',
    text: 'Does the LTV include expansion revenue, and has any of it happened yet?',
    why: 'Net revenue retention above a hundred percent makes LTV much larger and is a genuine strength when it is observed. Included as a projection it quietly doubles the number nobody has checked.',
    grounded: false,
  },
  {
    id: 'cohort',
    text: 'What does this look like for your oldest cohort rather than for the average?',
    why: 'The average mixes customers acquired last month, who have had no chance to leave, with those who have. Older cohorts are the only ones carrying real information about lifetime.',
    grounded: false,
  },
];

export function unitQuestionsFor(result: UnitEconomics, input: UnitEconomicsInput): Question[] {
  const grounded: Question[] = [];

  if (result.lifetimeExceedsHistory && result.averageLifetimeMonths !== null) {
    // The page's whole reason for existing, phrased with both numbers in it —
    // the specificity is what makes it land rather than lecture.
    grounded.push({
      id: 'lifetime-vs-history',
      text: `This assumes the average customer stays ${result.averageLifetimeMonths.toFixed(0)} months. You have been operating ${result.monthsOperating.toFixed(0)}. What is the longest anybody has actually stayed?`,
      why: 'LTV is a forecast in the shape of a measurement. Where the assumed lifetime runs past the company\'s own age, no customer has yet had the opportunity to prove it, which does not make the figure false, but does make it a projection, and the strongest version of the answer says so first.',
      grounded: true,
    });
  }

  if (result.averageLifetimeMonths === null) {
    grounded.push({
      id: 'no-churn',
      text: 'There is no churn in this model. Is that a number nobody has, or a number nobody has looked for?',
      why: 'Zero churn produces an infinite lifetime and an infinite LTV, so the ratio stops meaning anything. It is nearly always an unfilled field rather than a result, and the honest placeholder is the worst month you have had.',
      grounded: true,
    });
  }

  if (result.ratio !== null && result.ratio > SUSPICIOUS_RATIO) {
    grounded.push({
      id: 'too-efficient',
      text: 'A ratio this comfortable usually means acquisition is under-funded rather than unusually efficient. What stops you spending more?',
      why: 'Somebody funding growth reads a very high ratio as money left on the table: if a customer returns five times what they cost, the question is why you are not buying more of them. The answer is normally a channel constraint, and naming it turns a suspicious number into a credible one.',
      grounded: true,
    });
  } else if (result.ratio !== null && result.ratio < THIN_RATIO) {
    grounded.push({
      id: 'thin-ratio',
      text: 'Under three to one is where the model itself gets questioned rather than the inputs. Which side moves: the value or the cost?',
      why: 'Three to one is the convention, not a law, and plenty of businesses run below it deliberately while a channel matures. What gets asked is whether you know which lever you are pulling and by when.',
      grounded: true,
    });
  }

  if (result.paybackMonths !== null && result.paybackMonths > SLOW_PAYBACK) {
    grounded.push({
      id: 'slow-payback',
      text: `It takes ${result.paybackMonths.toFixed(0)} months to get the acquisition cost back. What funds the gap in the meantime?`,
      why: 'Payback is the cash question and the ratio is the profitability one; a business can look excellent on the second and run out of money on the first. Past a year, every new customer is a hole in the bank balance before they are an asset.',
      grounded: true,
    });
  }

  if (input.grossMarginPercent > 0 && input.grossMarginPercent < THIN_MARGIN) {
    grounded.push({
      id: 'thin-margin',
      text: `At ${input.grossMarginPercent.toFixed(0)}% margin, most of what a customer pays goes straight back out. Is that structural or is it early?`,
      why: 'Margin is the multiplier on everything here: it scales LTV and payback together. Whether it improves with volume is the difference between a business that gets better as it grows and one that gets bigger.',
      grounded: true,
    });
  }

  if (input.cac <= 0 && input.monthlyRevenuePerCustomer > 0) {
    grounded.push({
      id: 'free-growth',
      text: 'There is no acquisition cost here. Is growth genuinely free, or is somebody\'s time not being counted?',
      why: 'Organic and word-of-mouth growth are real and they are rarely free: founder selling time, content, community work and support all cost something. A zero makes the ratio infinite and the slide unreadable.',
      grounded: true,
    });
  }

  return [...grounded, ...STANDARD_UNIT_QUESTIONS].slice(0, MOST);
}
