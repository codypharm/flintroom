import type { BreakEven, BreakEvenInput } from './break-even';
import type { Question } from './question';

/**
 * What gets asked about a break-even figure.
 *
 * Usually by a bank, a partner or the owner themselves at two in the morning.
 * The number on the screen is a monthly average, and almost every question
 * here is really about the ways an average lies: the month that is quiet, the
 * cost that is not fixed, the customer who has not paid yet.
 */

const MOST = 7;

/** Under this, most of the month is spent covering costs. */
const THIN_SAFETY = 20;

/** Past this, the business is running on very little of its own capacity. */
const LATE_DAY = 24;

/** Asked of every break-even figure ever quoted. */
export const STANDARD_BREAK_EVEN_QUESTIONS: Question[] = [
  {
    id: 'which-costs-fixed',
    text: 'Which of those fixed costs are actually fixed?',
    why: 'Rent and salaries are. Contractors, commission, delivery, payment fees and most software are not: they move with volume and belong on the other side of the calculation. A cost filed as fixed when it is not moves break-even in the flattering direction.',
    grounded: false,
  },
  {
    id: 'own-salary',
    text: 'Is your own pay in the fixed costs?',
    why: 'A break-even that excludes the founder\'s living costs is a break-even for the business and not for the person running it. The two figures are often far apart, and only one of them decides whether this is sustainable.',
    grounded: false,
  },
  {
    id: 'seasonality',
    text: 'Does every month look like this one?',
    why: 'Break-even is computed on an average month and paid in real ones. A business that clears it comfortably across a year can still have three months that do not, and those are the months that need cash rather than arithmetic.',
    grounded: false,
  },
  {
    id: 'cash-timing',
    text: 'Break-even is about profit. When does the money actually arrive?',
    why: 'A profitable month with sixty-day payment terms still empties the bank. Plenty of businesses have gone under above their break-even point, and the gap between the two is timing rather than performance.',
    grounded: false,
  },
];

export function breakEvenQuestionsFor(result: BreakEven, input: BreakEvenInput): Question[] {
  const grounded: Question[] = [];

  if (result.salesShort !== null) {
    grounded.push({
      id: 'short',
      text: `You are about ${Math.ceil(result.salesShort)} sales a month short of covering costs. Which lever is nearest: price, volume, or the fixed costs themselves?`,
      why: 'All three work and they take very different amounts of time. Price moves immediately and risks volume; volume takes a quarter to build; cutting fixed costs is the fastest and the hardest to undo. Naming which one you are pulling is what turns a gap into a plan.',
      grounded: true,
    });
  }

  if (result.breakEvenUnits === null && input.price > 0) {
    grounded.push({
      id: 'no-contribution',
      text: 'There is no margin on a sale here, so no number of them covers the fixed costs. Is the margin missing, or is it genuinely zero?',
      why: 'A missing margin is the most common empty field on this kind of form. A genuinely zero one means every sale is made at cost, and the fixed costs are being paid by something other than the business.',
      grounded: true,
    });
  }

  if (result.marginOfSafetyPercent !== null && result.marginOfSafetyPercent > 0 && result.marginOfSafetyPercent < THIN_SAFETY) {
    grounded.push({
      id: 'thin-safety',
      text: `Sales could only fall about ${result.marginOfSafetyPercent.toFixed(0)}% before this stops working. What would a bad month look like?`,
      why: 'One lost customer, one quiet month or one late invoice is inside that gap. The useful version of this answer is a specific bad month you have already had, rather than a percentage.',
      grounded: true,
    });
  }

  if (result.breakEvenDay !== null && result.breakEvenDay > LATE_DAY) {
    grounded.push({
      id: 'late-day',
      text: `You do not start earning until day ${Math.round(result.breakEvenDay)}. What is the fixed cost you would remove first?`,
      why: 'When most of the month goes on covering costs, the fastest change is usually on the cost side rather than the sales side, and knowing which line you would cut before you need to is what makes it survivable.',
      grounded: true,
    });
  }

  if (result.profitableDays !== null && result.profitableDays > 20) {
    grounded.push({
      id: 'early-day',
      text: `Costs are covered by day ${Math.round(result.breakEvenDay!)}, so most of the month is profit. What stops you spending more to grow?`,
      why: 'A break-even reached this early usually means either genuine operating leverage or fixed costs that are lighter than the business needs. Both are worth knowing which, because only one of them scales.',
      grounded: true,
    });
  }

  if (input.monthlyVolume <= 0 && input.monthlyFixedCosts > 0) {
    grounded.push({
      id: 'no-volume',
      text: 'How many sales does a normal month actually bring? Without it, this is a target rather than a position.',
      why: 'The unit count alone says what you need. Adding what you currently do says whether you are above or below it, which is the question that was really being asked.',
      grounded: true,
    });
  }

  return [...grounded, ...STANDARD_BREAK_EVEN_QUESTIONS].slice(0, MOST);
}
