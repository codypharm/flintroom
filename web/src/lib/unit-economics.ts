/**
 * What a customer is worth, and how long you are assuming they stay.
 *
 * The output people quote is the ratio — "our LTV to CAC is four to one" —
 * and it is the softest number in any deck, because **LTV assumes a customer
 * lifetime nobody has lived yet**. Compute it from 3% monthly churn and you
 * have assumed the average customer stays 33 months, which is nearly three
 * years. Most companies quoting that have not existed for three years.
 *
 * So `averageLifetimeMonths` beside `monthsOperating` is the point of this
 * module. The ratio is not wrong; it is a forecast wearing the clothes of a
 * measurement, and naming the duration it rests on is what turns it back into
 * a claim somebody can defend.
 *
 * Two smaller things it refuses to get wrong, both of which are common:
 * value is gross profit rather than revenue, and monthly churn compounds into
 * an annual figure rather than multiplying by twelve.
 */

export interface UnitEconomicsInput {
  monthlyRevenuePerCustomer: number;
  grossMarginPercent: number;
  /** Monthly. The annual equivalent is derived, never asked for. */
  monthlyChurnPercent: number;
  /** All-in cost to acquire one customer. */
  cac: number;
  /** How long the company has been running, which is what the claim is measured against. */
  monthsOperating: number;
}

export interface UnitEconomics {
  /** Gross profit per customer per month. Revenue is not value. */
  monthlyContribution: number;
  /**
   * One over churn. `null` when churn is zero — nobody ever leaving is an
   * unfilled field rather than an excellent result, and reporting an enormous
   * lifetime there would flatter somebody into nonsense.
   */
  averageLifetimeMonths: number | null;
  ltv: number | null;
  /** `null` when nothing was spent to acquire anybody. */
  ratio: number | null;
  /** `null` when a customer contributes nothing, because it does not pay back. */
  paybackMonths: number | null;
  /** Compounded, not multiplied. 3% a month is 31% a year, not 36%. */
  annualChurnPercent: number;
  /** The headline: the assumed lifetime is longer than the company is old. */
  lifetimeExceedsHistory: boolean;
  monthsOperating: number;
}

function number(value: number): number {
  return Number.isFinite(value) ? value : 0;
}

export function unitEconomics(raw: UnitEconomicsInput): UnitEconomics {
  const revenue = Math.max(0, number(raw.monthlyRevenuePerCustomer));

  // You cannot keep more of a sale than you charged for it.
  const margin = Math.min(100, Math.max(0, number(raw.grossMarginPercent))) / 100;

  // Losing everybody every month is the floor: a one-month lifetime. Above
  // that the arithmetic stops describing anything.
  const churn = Math.min(100, Math.max(0, number(raw.monthlyChurnPercent))) / 100;

  const cac = Math.max(0, number(raw.cac));
  const monthsOperating = Math.max(0, number(raw.monthsOperating));

  const monthlyContribution = revenue * margin;

  const averageLifetimeMonths = churn > 0 ? 1 / churn : null;
  const ltv = averageLifetimeMonths === null ? null : monthlyContribution * averageLifetimeMonths;

  return {
    monthlyContribution,
    averageLifetimeMonths,
    ltv,
    ratio: ltv !== null && cac > 0 ? ltv / cac : null,
    paybackMonths: monthlyContribution > 0 && cac > 0 ? cac / monthlyContribution : null,
    annualChurnPercent: (1 - (1 - churn) ** 12) * 100,
    lifetimeExceedsHistory:
      averageLifetimeMonths !== null && monthsOperating > 0 && averageLifetimeMonths > monthsOperating,
    monthsOperating,
  };
}
