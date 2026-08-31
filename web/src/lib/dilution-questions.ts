import { dilute, type Dilution, type DilutionInput } from './dilution';
import type { Question } from './question';

/**
 * What to ask before you sign.
 *
 * The runway page frames its list as what gets asked *of* you. This one runs
 * the other way, and deliberately: dilution is not something you are
 * interrogated about, it is something you negotiate. The useful questions here
 * are the ones a founder should be putting to the other side of the table, and
 * most of them are only obvious once you have seen where the points went.
 *
 * Same two rules as everywhere else. Every line is a question — nothing on a
 * Flintroom page returns a verdict, and "your pool is too big" is a verdict.
 * And the grounded ones come first, because a question about your own term
 * sheet reads as having been listened to.
 */

const MOST = 7;

/** A pool sized past this is a hiring plan rather than a round number. */
const LARGE_POOL = 15;

/** Below half, the questions stop being about money and start being about control. */
const CONTROL_LINE = 50;

/**
 * Asked of every term sheet, in this order.
 *
 * Exported because the page arrives with empty fields, so there is nothing to
 * ground anything in yet. These four are worth asking about any round.
 */
export const STANDARD_DILUTION_QUESTIONS: Question[] = [
  {
    id: 'pool-purpose',
    text: 'What is the option pool actually for — which roles, over what period?',
    why: 'A pool is sized from a hiring plan, and a plan can be discussed. A round number cannot, which is why the number usually arrives without one attached.',
    grounded: false,
  },
  {
    id: 'everything-converting',
    text: 'Does this include everything that converts, or are there notes outside it?',
    why: 'A forgotten note is the most common reason a founder\'s real post-round number differs from the one they walked in with. Convertible notes, advisor equity and side letters all land at the same moment.',
    grounded: false,
  },
  {
    id: 'next-round',
    text: 'What does your number look like after the round after this one, on the same terms?',
    why: 'Dilution compounds, and the decision that matters is rarely this round in isolation. Running it twice is the cheapest planning anybody does.',
    grounded: false,
  },
  {
    id: 'pro-rata',
    text: 'Who has pro-rata rights, and what do they cost you if everyone exercises them?',
    why: 'Existing holders taking their pro-rata in the next round is dilution you have already agreed to and have not yet counted.',
    grounded: false,
  },
];

export function dilutionQuestionsFor(result: Dilution, input: DilutionInput): Question[] {
  const grounded: Question[] = [];
  const notes = input.safes.filter((note) => note.amount > 0);

  if (input.poolPre && input.poolPercent > 0) {
    // The counterfactual is computed rather than described, because the size of
    // the difference is the entire argument and it varies enormously.
    const asPost = dilute({ ...input, poolPre: false });
    const worth = asPost.yourAfter - result.yourAfter;

    grounded.push({
      id: 'pool-side',
      text: `The pool is coming out of your side of the table. What is the number if it goes in post-money instead?`,
      why: `On these figures, ${worth.toFixed(1)} points. A pre-money pool dilutes the people already there and leaves the incoming investor at exactly their percentage; a post-money one is shared. Which side it sits on is negotiable, and it is usually asked for pre-money because that is the default nobody questions.`,
      grounded: true,
    });
  }

  if (input.poolPercent > LARGE_POOL) {
    grounded.push({
      id: 'pool-size',
      text: 'A pool this size is a hiring plan. Whose plan is it, and has anyone written it down?',
      why: 'Pools above about fifteen percent are usually sized to cover a year of hiring plus a margin. Asking for the roles turns a round number into a conversation about the plan, which is a conversation you can win.',
      grounded: true,
    });
  }

  if (result.attribution.pool > result.attribution.investor && input.poolPercent > 0) {
    grounded.push({
      id: 'pool-outweighs',
      text: 'The pool is costing you more than the money is. Is that the trade you meant to make?',
      why: 'It is a common shape and almost never the one a founder expects walking in — the negotiation goes to the valuation while the larger number sits in a different line of the same term sheet.',
      grounded: true,
    });
  }

  if (notes.length > 0 && result.attribution.safes > result.attribution.investor) {
    grounded.push({
      id: 'safes-outweigh',
      text: 'More of this comes from notes you already signed than from the money you are raising. Was that priced in?',
      why: 'Caps agreed eighteen months ago convert at today\'s round, and a low cap on a good round is a large slice. It is not a problem to fix, but it is a number to know before you negotiate the new one.',
      grounded: true,
    });
  }

  if (notes.some((note) => note.kind === 'pre') && notes.some((note) => note.kind === 'post')) {
    grounded.push({
      id: 'mixed-notes',
      text: 'You are holding both pre- and post-money notes. Does everyone who signed one know which they have?',
      why: 'They dilute completely differently, and holders of the older pre-money notes are often surprised at conversion. Finding that out at the closing is worse than finding it out now.',
      grounded: true,
    });
  }

  if (notes.some((note) => note.cap <= 0 && note.discountPercent > 0)) {
    grounded.push({
      id: 'uncapped',
      text: 'One of these notes is uncapped. Is the holder expecting a cap that is not written down?',
      why: 'An uncapped note is priced entirely by this round, so the holder carries none of the early risk they may believe they took. It is the version most likely to produce an argument at conversion.',
      grounded: true,
    });
  }

  if (result.yourAfter < CONTROL_LINE && result.yourBefore >= CONTROL_LINE) {
    grounded.push({
      id: 'below-half',
      text: 'This round takes you under half. Does anything in your governance turn on that line?',
      why: 'Ordinary share majority, board composition and protective provisions are separate documents that sometimes reference it. The percentage matters less than what is attached to it.',
      grounded: true,
    });
  }

  return [...grounded, ...STANDARD_DILUTION_QUESTIONS].slice(0, MOST);
}
