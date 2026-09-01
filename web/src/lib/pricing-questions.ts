import type { PriceChange, PriceChangeInput } from './pricing';
import type { Question } from './question';

/**
 * What gets asked about a price change.
 *
 * Mostly by the person who has to sign it off, and sometimes by the owner
 * asking themselves. The arithmetic on this page answers "how much can we
 * afford to lose"; none of these ask that, because it is already on the
 * screen. They ask the things the number cannot: who leaves, who is told,
 * and whether the price can ever come back.
 */

const MOST = 7;

/** Past this, the change is a repositioning rather than a price move. */
const LARGE_CHANGE = 20;

/** Below this, the margin has little room for anything else to move. */
const THIN_MARGIN = 20;

/**
 * Losing more than this and still being ahead is worth interrogating.
 *
 * Twenty rather than thirty. The page's own worked example — a 10% rise at a
 * 30% margin — tolerates losing 25%, so a threshold of thirty sat just above
 * the case the tool exists to show and the question never fired on it.
 */
const WIDE_TOLERANCE = 20;

/** Asked of every price change anybody has ever proposed. */
export const STANDARD_PRICING_QUESTIONS: Question[] = [
  {
    id: 'existing-or-new',
    text: 'Does this apply to existing customers, or only to new ones?',
    why: 'The most commonly skipped decision, and it changes the arithmetic completely: a new-customers-only change earns nothing from the base you already have, and takes far longer to show up. It also decides whether anybody has to be told at all.',
    grounded: false,
  },
  {
    id: 'notice',
    text: 'Who is told, how far ahead, and by whom?',
    why: 'A price change discovered on an invoice is a different event from one announced with notice, even when the number is identical. Most of the churn a rise produces comes from how it arrived rather than from what it was.',
    grounded: false,
  },
  {
    id: 'contracts',
    text: 'Which customers are on terms that fix the old price, and until when?',
    why: 'Annual contracts, grandfathered rates and anything with a price-protection clause simply will not move. They are usually the largest accounts, which means the revenue this change actually touches is smaller than the whole book.',
    grounded: false,
  },
  {
    id: 'reversibility',
    text: 'If it does not land, how do you undo it?',
    why: 'Price moves are not symmetrical. Coming down is easy and reads as a concession; going back up after a cut reads as a betrayal and usually costs more customers than the original rise would have.',
    grounded: false,
  },
];

export function pricingQuestionsFor(result: PriceChange, input: PriceChangeInput): Question[] {
  const grounded: Question[] = [];
  const move = Math.abs(input.changePercent);
  const tolerance = result.volumeChangeNeededPercent;

  if (result.belowCost) {
    grounded.push({
      id: 'below-cost',
      text: 'At this discount every sale is made below cost. What is the argument for it that is not volume?',
      why: 'There are real ones (clearing stock, buying a strategic logo, entering a market) and they are all arguments about something other than this quarter. What does not survive is a discount presented as a growth move when each additional sale deepens the loss.',
      grounded: true,
    });
  }

  if (!result.raising && move > 0 && !result.belowCost && tolerance !== null) {
    grounded.push({
      id: 'discount-demand',
      text: `This needs ${tolerance.toFixed(0)}% more volume just to stand still. Where does that come from?`,
      why: 'A discount is a bet that cheaper brings enough new customers to cover the ones already paying more. The size of that bet is rarely calculated before the decision, and it is almost always larger than it feels.',
      grounded: true,
    });
  }

  if (result.raising && tolerance !== null && Math.abs(tolerance) > WIDE_TOLERANCE) {
    grounded.push({
      id: 'wide-tolerance',
      text: `You could lose ${Math.abs(tolerance).toFixed(0)}% of customers and still be ahead. Which of them would go first?`,
      why: 'The average customer does not leave; specific ones do, and they are rarely a random sample. If the ones most likely to go are also the ones who refer, or the ones a case study depends on, the arithmetic understates what is at stake.',
      grounded: true,
    });
  }

  if (move > LARGE_CHANGE) {
    grounded.push({
      id: 'repositioning',
      text: 'A move this size is a repositioning rather than a price change. Does what you offer change with it?',
      why: 'Past roughly a fifth, customers stop reading a new price as the same product costing more and start asking what is different. Left unanswered, they answer it themselves, and usually unfavourably.',
      grounded: true,
    });
  }

  if (input.grossMarginPercent > 0 && input.grossMarginPercent < THIN_MARGIN) {
    grounded.push({
      id: 'thin-margin',
      text: `At ${input.grossMarginPercent.toFixed(0)}% margin there is very little room between price and cost. What happens to this if costs move too?`,
      why: 'A thin margin makes a price change powerful and fragile at the same time: a small rise transforms contribution, and a small cost increase erases it. Both effects are larger than they look from the percentages.',
      grounded: true,
    });
  }

  if (result.customersAtStake !== null) {
    grounded.push({
      id: 'named-customers',
      text: `That is about ${Math.round(result.customersAtStake)} customers. Could you name the first ten?`,
      why: 'A percentage is a threshold; ten names is a plan. Whoever can list them usually also knows which are at genuine risk, and that conversation is more useful than the percentage that started it.',
      grounded: true,
    });
  }

  return [...grounded, ...STANDARD_PRICING_QUESTIONS].slice(0, MOST);
}
