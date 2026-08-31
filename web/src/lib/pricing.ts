/**
 * What a price change can afford to cost you in customers.
 *
 * The question people ask before changing a price is "will they leave?", which
 * nobody can answer. The question they can answer, and almost never do, is
 * **how many would have to leave before the change stopped being worth it** —
 * and that is arithmetic rather than judgement.
 *
 * It is surprising in both directions. At a 30% margin, a 10% rise survives
 * losing a quarter of the customers. A 10% discount needs half again as many
 * to stand still. The discount half is the more useful, because discounting is
 * the more common decision and by far the more damaging, and the number that
 * makes that concrete is rarely on the table when it is being decided.
 *
 * **This does not predict whether anybody will leave.** That is elasticity, it
 * needs data this page cannot ask for, and inventing it would be inventing the
 * most important input. What is returned is the threshold, not the outcome.
 */

export interface PriceChangeInput {
  price: number;
  /** Gross margin at the current price. Percentage, not a unit cost. */
  grossMarginPercent: number;
  /** Positive to raise, negative to cut. */
  changePercent: number;
  /** Optional. Turns the threshold from a share into a number of customers. */
  monthlyVolume: number;
}

export interface PriceChange {
  newPrice: number;
  /** Held still across the change: a new price does not move what it costs. */
  unitCost: number;
  contributionBefore: number;
  contributionAfter: number;
  /**
   * The volume change that leaves total contribution exactly where it was, as
   * a percentage. Negative is what you can afford to lose; positive is what a
   * discount demands you gain.
   *
   * `null` when there is no answer — no margin to work with, or a discount
   * deeper than the margin, where no volume rescues a sale made below cost.
   */
  volumeChangeNeededPercent: number | null;
  /** How many customers that percentage is, when volume was given. */
  customersAtStake: number | null;
  raising: boolean;
  /** The discount is at or past the margin, so every sale loses money. */
  belowCost: boolean;
}

function number(value: number): number {
  return Number.isFinite(value) ? value : 0;
}

export function priceChange(raw: PriceChangeInput): PriceChange {
  const price = Math.max(0, number(raw.price));
  const margin = Math.min(100, Math.max(0, number(raw.grossMarginPercent))) / 100;
  const change = number(raw.changePercent) / 100;
  const volume = Math.max(0, number(raw.monthlyVolume));

  // The cost of the thing is what it is. Recomputing it from the new price is
  // the classic error here, and it makes every price rise look free.
  const unitCost = price * (1 - margin);
  const newPrice = Math.max(0, price * (1 + change));

  const contributionBefore = price - unitCost;
  const contributionAfter = newPrice - unitCost;

  // At or below cost there is no volume that helps: every additional sale
  // deepens the loss. Reporting a very large percentage would imply a number
  // exists somewhere out there, and it does not.
  const belowCost = contributionAfter <= 0 && change < 0;

  const volumeChangeNeededPercent =
    contributionBefore > 0 && contributionAfter > 0
      ? (contributionBefore / contributionAfter - 1) * 100
      : null;

  return {
    newPrice,
    unitCost,
    contributionBefore,
    contributionAfter,
    volumeChangeNeededPercent,
    customersAtStake:
      volumeChangeNeededPercent !== null && volume > 0
        ? Math.abs((volumeChangeNeededPercent / 100) * volume)
        : null,
    raising: change > 0,
    belowCost,
  };
}
