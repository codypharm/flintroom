/**
 * Whether a business case pays for itself, and how much of it has to land.
 *
 * The ordinary calculation is `(gain − cost) / cost`, and it produces the one
 * confident number that every business case is presented with and every
 * business case is destroyed by. The first hostile question in the room is
 * never "what is the ROI", it is **"and what if you only get half of that?"**
 *
 * So the figure this module exists for is `breakEvenBenefitPercent`: the share
 * of the projected upside at which the case stops paying for itself. It turns
 * an argument about an optimistic forecast into an argument about a floor,
 * which is a much easier argument to win and a much harder one to attack.
 *
 * No IRR. It needs iteration, it is widely misunderstood, and nobody has ever
 * won a budget meeting with it.
 */

/** Ten years of months. Past that a schedule is a wall rather than a chart. */
const MOST_MONTHS = 120;

export interface RoiInput {
  /** Paid today: implementation, migration, licences, the first invoice. */
  oneOffCost: number;
  /** Everything the thing costs every month once it is running. */
  monthlyCost: number;
  /** The benefit at full run rate, not on day one. See `rampMonths`. */
  monthlyBenefit: number;
  /**
   * Months to reach that run rate, ramping linearly from zero.
   *
   * Almost every ROI calculator assumes full benefit in month one, which is
   * never true of anything that has to be rolled out and learned — and "when
   * does this actually start paying?" is the second question asked of a case,
   * right after the sensitivity one.
   */
  rampMonths: number;
  horizonMonths: number;
  /** Annual, as a percentage. Converted to a monthly rate by compounding. */
  discountRatePercent: number;
}

export interface RoiMonth {
  month: number;
  benefit: number;
  cost: number;
  net: number;
  /** Running total of undiscounted net, which is what payback is read from. */
  cumulative: number;
}

export interface Roi {
  totalCost: number;
  totalBenefit: number;
  netBenefit: number;
  /** Return against spend, over the horizon, undiscounted. */
  roiPercent: number;
  /** Months until the running total turns positive. `null` if it never does. */
  paybackMonths: number | null;
  npv: number;
  /**
   * The share of the projected benefit that has to land for the case to break
   * even, as a percentage. Above 100 means it does not pay back at all on
   * these figures — reported honestly rather than clamped, because "you need
   * 140% of the projected benefit" is the useful sentence.
   *
   * `null` when there is no benefit to scale: nothing multiplied by anything
   * is still nothing, and reporting 0% there would claim the case breaks even
   * for free.
   */
  breakEvenBenefitPercent: number | null;
  schedule: RoiMonth[];
}

function number(value: number): number {
  return Number.isFinite(value) ? value : 0;
}

export function businessCase(raw: RoiInput): Roi {
  const oneOffCost = Math.max(0, number(raw.oneOffCost));
  const monthlyCost = Math.max(0, number(raw.monthlyCost));
  const monthlyBenefit = Math.max(0, number(raw.monthlyBenefit));
  const ramp = Math.max(0, number(raw.rampMonths));
  const horizon = Math.min(MOST_MONTHS, Math.max(1, Math.round(number(raw.horizonMonths)) || 1));

  // Compounded rather than divided by twelve. The difference is small and the
  // convention is the defensible one — a finance team reading over somebody's
  // shoulder will recognise it.
  const annual = Math.max(0, number(raw.discountRatePercent)) / 100;
  const monthlyRate = annual > 0 ? (1 + annual) ** (1 / 12) - 1 : 0;

  const schedule: RoiMonth[] = [];

  let cumulative = 0;
  let totalBenefit = 0;
  let paybackMonths: number | null = null;

  // Present values, kept separately so the break-even share falls out in
  // closed form: benefit scales linearly, everything else is fixed.
  let pvBenefit = 0;
  let pvCost = 0;

  for (let month = 1; month <= horizon; month += 1) {
    const reached = ramp > 0 ? Math.min(1, month / ramp) : 1;
    const benefit = monthlyBenefit * reached;
    const net = benefit - monthlyCost;

    const opening = cumulative;
    cumulative += net;
    totalBenefit += benefit;

    const discount = (1 + monthlyRate) ** month;
    pvBenefit += benefit / discount;
    pvCost += monthlyCost / discount;

    // The month it crosses zero, with the fraction of that month it took —
    // "4.5 months" is a different conversation from "month 5".
    if (paybackMonths === null && cumulative >= oneOffCost && net > 0) {
      paybackMonths = month - 1 + (oneOffCost - opening) / net;
    }

    schedule.push({ month, benefit, cost: monthlyCost, net, cumulative: cumulative - oneOffCost });
  }

  const totalCost = oneOffCost + monthlyCost * horizon;
  const netBenefit = totalBenefit - totalCost;

  // The one-off is not discounted: it is paid today. Discounting money you are
  // about to spend is the classic sign error in a hand-rolled NPV.
  const npv = pvBenefit - pvCost - oneOffCost;

  return {
    totalCost,
    totalBenefit,
    netBenefit,
    roiPercent: totalCost > 0 ? (netBenefit / totalCost) * 100 : 0,
    paybackMonths,
    npv,
    breakEvenBenefitPercent: pvBenefit > 0 ? ((oneOffCost + pvCost) / pvBenefit) * 100 : null,
    schedule,
  };
}
