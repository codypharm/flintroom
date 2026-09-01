import type { Question } from './question';
import type { Roi, RoiInput } from './roi';

/**
 * What gets asked about a business case.
 *
 * The runway page's framing rather than the dilution page's, and the
 * distinction is real: defending a budget request is an interrogation, where a
 * term sheet is a negotiation. These are the questions coming at you across
 * the table, from people whose own budget is the other half of the same pot.
 *
 * Same rules everywhere else obeys. Every line is a question, and nothing here
 * grades the case — "this is a weak return" is a verdict, and the product does
 * not return verdicts.
 */

const MOST = 7;

/** Above this, the case needs nearly everything to land. */
const FRAGILE = 80;

/** Below this, the number is good enough to invite suspicion. */
const TOO_GOOD = 40;

/** Beyond two years, payback crosses somebody's planning cycle. */
const SLOW_PAYBACK = 24;

/** Asked of every business case ever put in front of a committee. */
export const STANDARD_ROI_QUESTIONS: Question[] = [
  {
    id: 'do-nothing',
    text: 'What does doing nothing cost? Not zero: what is the price of carrying on as we are?',
    why: 'Every case is implicitly a comparison, and the alternative is rarely free. A case that has priced the status quo is arguing about a difference; one that has not is arguing about a spend.',
    grounded: false,
  },
  {
    id: 'who-owns-it',
    text: 'Who owns the benefit, and will they carry it in their own numbers?',
    why: 'A saving nobody has agreed to be measured on tends not to appear. The question separates a benefit somebody has signed up to from one that was estimated on their behalf.',
    grounded: false,
  },
  {
    id: 'internal-time',
    text: 'Is internal time in the cost, or only what leaves the building?',
    why: 'The people who implement, run and support the thing are the most commonly omitted line, because their salaries are already being paid. Finance will notice.',
    grounded: false,
  },
  {
    id: 'single-assumption',
    text: 'Which single assumption, if it turned out to be wrong, takes this to zero?',
    why: 'Naming it first is what separates a case somebody has stress-tested from one they have only built. It is also the question that gets asked whether or not you raise it.',
    grounded: false,
  },
];

export function roiQuestionsFor(result: Roi, input: RoiInput): Question[] {
  const grounded: Question[] = [];
  const breakEven = result.breakEvenBenefitPercent;

  if (breakEven !== null && breakEven > 100) {
    grounded.push({
      id: 'never-pays',
      text: 'On these figures it does not pay back at all. Is there a case for it that is not financial?',
      why: 'Plenty of things are worth doing on risk, compliance or capability grounds and lose on a spreadsheet. What does not survive is a case presented as financial when the arithmetic says otherwise.',
      grounded: true,
    });
  } else if (breakEven !== null && breakEven > FRAGILE) {
    grounded.push({
      id: 'fragile',
      text: `Nearly all of the projected benefit has to land for this to work. What does it look like at sixty percent?`,
      why: 'A case that only clears the bar at full delivery has no room in it, and the person opposite you knows that forecasts rarely arrive whole. Bringing the reduced number yourself is the strongest version of the answer.',
      grounded: true,
    });
  } else if (breakEven !== null && breakEven < TOO_GOOD) {
    grounded.push({
      id: 'too-good',
      text: 'This pays back even if most of the projected benefit never arrives. What is being left out?',
      why: 'A very comfortable margin usually means a cost line is missing rather than that the case is unusually good. Internal time, change management and the thing being replaced are the three that go absent most often.',
      grounded: true,
    });
  }

  if (result.paybackMonths === null) {
    grounded.push({
      id: 'no-payback',
      text: 'It does not break even inside the horizon you set. Is the horizon wrong, or is the case?',
      why: 'Both are legitimate answers and they lead to completely different conversations. Deciding which one you are making before you walk in is the point.',
      grounded: true,
    });
  } else if (result.paybackMonths > SLOW_PAYBACK) {
    grounded.push({
      id: 'slow-payback',
      text: 'Payback lands beyond two years. Whose planning cycle does that cross, and are they in the room?',
      why: 'Anything paying back past the next budget cycle is being approved by people who may not be there to see it. That is a governance question rather than a financial one, and it is usually the one that stalls a case.',
      grounded: true,
    });
  }

  if (input.rampMonths <= 0 && input.monthlyBenefit > 0) {
    grounded.push({
      id: 'no-ramp',
      text: 'This assumes the full benefit from month one. What actually happens in the first quarter?',
      why: 'Nothing that has to be installed, learned and adopted delivers at full rate immediately. A ramp makes the payback later and the case considerably harder to pick apart.',
      grounded: true,
    });
  }

  if (input.monthlyCost <= 0 && input.oneOffCost > 0) {
    grounded.push({
      id: 'no-running-cost',
      text: 'There is no running cost in this. Who maintains it, and is their time free?',
      why: 'A one-off cost with no ongoing line usually means support, licences or the person who owns it have not been counted. It is the first thing a finance partner looks for.',
      grounded: true,
    });
  }

  if (input.horizonMonths > 36) {
    grounded.push({
      id: 'long-horizon',
      text: `The horizon is doing a lot of work here. What does the case look like over three years?`,
      why: 'A longer horizon quietly improves every business case, so a non-standard one invites the question of why it was chosen. Three years is the length most committees expect.',
      grounded: true,
    });
  }

  return [...grounded, ...STANDARD_ROI_QUESTIONS].slice(0, MOST);
}
