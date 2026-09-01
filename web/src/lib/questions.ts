import type { Question } from './question';
import type { Runway, RunwayInput } from './runway';

/**
 * What the number invites.
 *
 * Any page on the internet can divide cash by burn. The reason to be on ours is
 * this list: the number is not the end of the exercise, it is the thing someone
 * is about to ask you about. That is the product in miniature, done silently and
 * in text, and it is deliberately a much smaller thing than the room.
 *
 * Two rules hold the tone, and both are the product's rules rather than this
 * page's. **Every line is a question.** Flintroom does not return verdicts, and
 * a calculator that told a founder their burn was high would be the scorecard
 * the whole positioning refuses to be. And **the grounded ones come first** —
 * a generic question at the top reads as a listicle; one drawn from what you
 * actually typed reads as having been listened to.
 *
 * `why` exists because this page serves somebody who has sat through ten of
 * these and somebody who has sat through none. The question alone serves the
 * first. The second needs to know who asks it and what a good answer sounds
 * like, and it costs the first reader a second to skip.
 */

export type { Question };

/**
 * Seven is a page you read standing up. Twelve is a page you close.
 *
 * Every conditional firing at once is a real set of inputs, not a hypothetical
 * — no revenue, flat burn, six weeks of cash is what a pre-seed founder types —
 * so the cap has to exist rather than be assumed away.
 */
const MOST = 7;

/** Under this, the conversation is about the round rather than the plan. */
const SHORT_MONTHS = 6;

/** Over this, the plan changes before the money does. */
const LONG_MONTHS = 24;

/**
 * Asked of every number, in this order, and the order is a priority.
 *
 * Exported because the page renders with empty fields (no seed company — a
 * pre-filled figure gets mistaken for one of your own), so on arrival there is
 * nothing to ground anything in. These four are what an empty page can honestly
 * show: they are asked of every runway number that has ever been quoted.
 */
export const STANDARD_QUESTIONS: Question[] = [
  {
    id: 'gross-or-net',
    text: 'Is that cash figure gross, or net of what you already owe?',
    why: 'Bank balance and available cash are different numbers. Payables, deferred payroll and a tax bill tend to land in the same quarter as everything else, and the gap between the two figures is where a stated runway quietly shortens.',
    grounded: false,
  },
  {
    id: 'committed-spend',
    text: 'Does the spend include the hires you have already made offers to?',
    why: 'An accepted offer is committed spend that has not reached a bank statement yet. It is the most common reason a runway figure moves a month after it was first quoted.',
    grounded: false,
  },
  {
    id: 'raise-slips',
    text: 'What is this number if the round takes a quarter longer than planned?',
    why: 'Processes slip. The answer separates a plan from a hope, and whoever is asking has watched a great many timelines move to the right.',
    grounded: false,
  },
  {
    id: 'single-line',
    text: 'Which single line item, if it doubled, moves this date the most?',
    why: 'Concentration risk in one sentence. If one vendor, one hire or one infrastructure bill can move the date on its own, it lands better when you name it before anyone else does.',
    grounded: false,
  },
];

export function questionsFor(result: Runway, input: RunwayInput): Question[] {
  const grounded: Question[] = [];

  if ((input.burnGrowthPercent ?? 0) === 0) {
    grounded.push({
      id: 'flat-burn',
      text: 'You have modelled flat spend. When was the last month yours did not move?',
      why: 'Flat burn is the assumption most plans make and few companies match. Naming the rate you actually expect is what turns a projection into a forecast somebody can hold you to.',
      grounded: true,
    });
  }

  if (input.monthlyRevenue <= 0) {
    grounded.push({
      id: 'no-revenue',
      text: 'There is no revenue in this model. Is that the stage, or a choice you would defend?',
      why: 'Pre-revenue is an ordinary answer at some stages and a conversation at others. What gets probed is whether it was chosen or arrived at.',
      grounded: true,
    });
  } else if ((input.revenueGrowthPercent ?? 0) === 0) {
    grounded.push({
      id: 'flat-revenue',
      text: 'Revenue is held flat here. If it is climbing, at what rate, and where does that rate come from?',
      why: 'A growth rate is a claim about the future and gets treated like one. The follow-up is almost always what the last three months actually did.',
      grounded: true,
    });
  }

  if (result.defaultAlive) {
    grounded.push({
      id: 'default-alive',
      text: 'This reaches profitable without a raise. Which assumption in it are you least sure of?',
      why: 'Default alive is a strong position and an easy one to overstate. The version that survives scrutiny names its own weakest input first.',
      grounded: true,
    });
  } else {
    grounded.push({
      id: 'default-dead',
      text: 'On these numbers, profitability arrives after the cash does. What closes the gap: the raise, the costs, or the revenue?',
      why: "Paul Graham's default alive or default dead, and it sits on most diligence lists because the answer decides whether the next round is a choice or a requirement.",
      grounded: true,
    });
  }

  if (result.months < SHORT_MONTHS) {
    grounded.push({
      id: 'short-runway',
      text: 'Under six months of cash. Who has already said yes?',
      why: 'At this range the conversation moves from the plan to the round itself. Named commitments answer it; a list of meetings in the diary does not.',
      grounded: true,
    });
  } else if (result.months > LONG_MONTHS) {
    grounded.push({
      id: 'long-runway',
      text: 'Over two years of cash. What milestone does that buy, rather than what date?',
      why: 'Past roughly two years the plan changes before the money does, so the figure people act on is the milestone the runway is meant to reach.',
      grounded: true,
    });
  }

  // Grounded first, then as much of the standard list as fits. Truncating the
  // universal end is the right way round: those questions are asked of every
  // company, so losing the fourth one costs this reader least.
  return [...grounded, ...STANDARD_QUESTIONS].slice(0, MOST);
}
