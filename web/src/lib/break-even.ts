/**
 * When the month starts paying for itself.
 *
 * The standard output of a break-even calculator is a unit count, which is
 * correct and forgettable. What an owner acts on is **the day of the month the
 * fixed costs are covered** — after which every sale is profit rather than
 * rent. Same move the runway page makes: a date is a fact you plan around, a
 * count is a number you have to convert first.
 *
 * It also reports the two things that make the count usable: how far sales
 * could fall before the business stops working, and — when the month does not
 * get there at all — how many sales short it is, rather than a day past the
 * end of the month.
 */

/** A month, for turning a share of volume into a day. Not a calendar. */
const DAYS = 30;

export interface BreakEvenInput {
  monthlyFixedCosts: number;
  /** What one sale is worth. Per unit, per seat, per job. */
  price: number;
  /** Margin at that price, so services with no unit cost still work. */
  grossMarginPercent: number;
  /** Sales in a typical month. Optional, and what the day depends on. */
  monthlyVolume: number;
}

export interface BreakEven {
  /** Price minus the direct cost of delivering it. */
  contributionPerSale: number;
  /** `null` when a sale contributes nothing — there is no number of units. */
  breakEvenUnits: number | null;
  breakEvenRevenue: number | null;
  /**
   * The day of a 30-day month the fixed costs are covered on, assuming sales
   * arrive evenly. `null` when the month never gets there, because "day 36" is
   * not an answer.
   */
  breakEvenDay: number | null;
  /** Days of the month left after that, which is where the profit is. */
  profitableDays: number | null;
  /** How far volume could fall before break-even. Negative when under water. */
  marginOfSafetyPercent: number | null;
  reachesBreakEven: boolean;
  /** Sales needed to reach it, when the month falls short. */
  salesShort: number | null;
}

function number(value: number): number {
  return Number.isFinite(value) ? value : 0;
}

export function breakEven(raw: BreakEvenInput): BreakEven {
  const fixed = Math.max(0, number(raw.monthlyFixedCosts));
  const price = Math.max(0, number(raw.price));
  const margin = Math.min(100, Math.max(0, number(raw.grossMarginPercent))) / 100;
  const volume = Math.max(0, number(raw.monthlyVolume));

  const contributionPerSale = price * margin;

  // No contribution means no number of sales covers anything. Reporting an
  // enormous count would imply one exists.
  const breakEvenUnits = contributionPerSale > 0 ? fixed / contributionPerSale : fixed === 0 ? 0 : null;

  const reaches = breakEvenUnits !== null && volume > 0 && volume >= breakEvenUnits;
  const share = breakEvenUnits !== null && volume > 0 ? breakEvenUnits / volume : null;

  return {
    contributionPerSale,
    breakEvenUnits,
    breakEvenRevenue: breakEvenUnits === null ? null : breakEvenUnits * price,
    breakEvenDay: reaches && share !== null ? share * DAYS : null,
    profitableDays: reaches && share !== null ? DAYS - share * DAYS : null,
    marginOfSafetyPercent:
      breakEvenUnits !== null && volume > 0 ? ((volume - breakEvenUnits) / volume) * 100 : null,
    reachesBreakEven: reaches,
    salesShort: breakEvenUnits !== null && volume > 0 && !reaches ? breakEvenUnits - volume : null,
  };
}
