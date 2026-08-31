/**
 * How long the money lasts.
 *
 * The published version of this calculation is cash ÷ net burn, and that is
 * what almost every runway calculator on the web computes. It is also wrong in
 * one specific way that matters: it assumes spend is flat, and nobody's is. A
 * founder who plans against the flat number is planning against a date that
 * has already moved.
 *
 * So this simulates month by month instead of dividing. That buys three things
 * the division cannot give: a real date rather than a count, a schedule you can
 * look at, and the case where you are profitable today and still run out —
 * which a division reports as infinite and a board meeting does not.
 *
 * No DOM, no clock. `from` is a parameter precisely so the tests assert facts
 * rather than something that starts failing in March.
 */

/** How many months of schedule are worth rendering. Beyond this it is a wall. */
const SCHEDULE_MONTHS = 60;

/**
 * Where the simulation gives up and calls it survival.
 *
 * A thousand years. Not a real horizon — a guard, so that a rounding artefact
 * or a spend that shrinks toward zero cannot spin the loop forever. Anything
 * that reaches it is "this does not end" by any measure a founder cares about.
 */
const HORIZON_MONTHS = 12_000;

export interface RunwayInput {
  /** Cash in the bank today. */
  cash: number;
  /** Everything going out in a month, gross. */
  monthlySpend: number;
  /** Everything coming in. */
  monthlyRevenue: number;
  /** Compounding month-on-month change in spend. 0 is flat, 5 is +5%/mo. */
  burnGrowthPercent: number;
  /**
   * Compounding month-on-month change in revenue.
   *
   * Optional, and it defaults to flat rather than to anything cheerful.
   * Omitting it has to mean "I am not claiming growth" — a calculator that
   * quietly assumes some flatters every user who leaves the field alone, and
   * this one is supposed to be the pessimistic reading.
   */
  revenueGrowthPercent?: number;
  /** The day the clock starts. Passed in, never read from the machine. */
  from: Date;
}

export interface RunwayMonth {
  /** 1-based, so month 1 is the month you are standing in. */
  month: number;
  spend: number;
  revenue: number;
  /** Positive is money leaving. Negative means this month paid for itself. */
  netBurn: number;
  /** Cash at the end of the month, floored at zero on the month it runs out. */
  closing: number;
}

export interface Runway {
  /** Fractional months. `Infinity` when the money does not run out. */
  months: number;
  /** The day it hits zero, or `null` when it does not. */
  endsOn: Date | null;
  neverRunsOut: boolean;
  /** 1-based month revenue first covers spend, or `null` if it never does. */
  profitableFrom: number | null;
  /**
   * Paul Graham's question, and the one on every diligence list: on this
   * trajectory and with no new money, do you reach profitable before zero.
   *
   * Deliberately NOT the same as `neverRunsOut`. Enormous cash and a tiny burn
   * survives any horizon worth simulating and is still default dead — nothing
   * in it ever pays for itself. Conflating the two is the easy bug, and it
   * would tell exactly the wrong founder they are fine.
   */
  defaultAlive: boolean;
  schedule: RunwayMonth[];
}

/** An empty field arrives as `NaN`, and "NaN months" is worse than a refusal. */
function number(value: number): number {
  return Number.isFinite(value) ? value : 0;
}

function daysIn(year: number, monthIndex: number): number {
  return new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate();
}

/**
 * `from` plus a fractional number of months.
 *
 * Whole months move the calendar; the remainder becomes days in the month it
 * lands in, so a third of February is shorter than a third of March. Overflow
 * is JavaScript's own — the 31st of a month plus one month lands in the next
 * one — which is the right answer often enough and never wrong by more than
 * three days.
 */
function addMonths(from: Date, months: number): Date {
  const whole = Math.floor(months);
  const rest = months - whole;

  const landed = new Date(
    Date.UTC(from.getUTCFullYear(), from.getUTCMonth() + whole, from.getUTCDate()),
  );

  if (rest > 0) {
    const days = daysIn(landed.getUTCFullYear(), landed.getUTCMonth());
    landed.setUTCDate(landed.getUTCDate() + Math.round(rest * days));
  }

  return landed;
}

/**
 * Clamped at zero rather than passed through. Somebody will type -150 into a
 * growth field to model deep cuts, and a factor below zero would have the line
 * cross into negative — a company paying money *in* every month, and a runway
 * that reads as decades.
 */
function growthFactor(percent: number): number {
  return Math.max(0, 1 + number(percent) / 100);
}

export function runway(input: RunwayInput): Runway {
  const spendFactor = growthFactor(input.burnGrowthPercent);
  const revenueFactor = growthFactor(input.revenueGrowthPercent ?? 0);

  let cash = Math.max(0, number(input.cash));
  let spend = Math.max(0, number(input.monthlySpend));
  let revenue = Math.max(0, number(input.monthlyRevenue));

  const schedule: RunwayMonth[] = [];
  let profitableFrom: number | null = null;

  for (let month = 1; month <= HORIZON_MONTHS; month += 1) {
    if (profitableFrom === null && revenue >= spend) {
      profitableFrom = month;
    }

    const netBurn = spend - revenue;

    if (netBurn > 0 && cash <= netBurn) {
      // It ends inside this month. The fraction is how much of the month the
      // remaining cash pays for — kept rather than rounded down, because 3.3
      // months is a different conversation from 3.
      const months = month - 1 + cash / netBurn;

      if (schedule.length < SCHEDULE_MONTHS) {
        schedule.push({ month, spend, revenue, netBurn, closing: 0 });
      }

      return {
        months,
        endsOn: addMonths(input.from, months),
        neverRunsOut: false,
        profitableFrom,
        // It ran out. Whether some earlier month happened to cover itself is
        // beside the point — the money is gone, so this is default dead.
        defaultAlive: false,
        schedule,
      };
    }

    cash -= netBurn; // Negative burn is a month that paid for itself.

    if (schedule.length < SCHEDULE_MONTHS) {
      schedule.push({ month, spend, revenue, netBurn, closing: cash });
    }

    spend *= spendFactor;
    revenue *= revenueFactor;
  }

  return {
    months: Infinity,
    endsOn: null,
    neverRunsOut: true,
    profitableFrom,
    defaultAlive: profitableFrom !== null,
    schedule,
  };
}
