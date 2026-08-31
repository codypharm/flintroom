/**
 * What a round actually costs you, and where the cost came from.
 *
 * Everything here is proportional, so it runs on percentages and never asks
 * for a share count. A founder holding SAFEs usually has no formal cap table
 * yet — they know they own 62% — and asking for authorised, issued and
 * outstanding is asking a question they would have to go and look up.
 *
 * **The model, stated plainly, because a calculator that hides its assumptions
 * is worse than one that has none.** The round is read the way a term sheet
 * reads it: the investor takes `raise / (preMoney + raise)` of the company, and
 * everybody else — founders, converting SAFEs, the new option pool — divides
 * what is left. SAFEs convert immediately before the money lands. A pre-money
 * pool is carved out of that same pre-money slice, which is precisely why it
 * leaves the investor untouched.
 *
 * **What it simplifies.** A SAFE with a discount is converted at an effective
 * valuation of `preMoney × (1 − discount)`, compared against its cap, with the
 * lower of the two winning because that is the one that buys more shares. Real
 * pre-money SAFE conversion with several notes is circular, and the convention
 * used here — each note prices off the pre-money valuation over the existing
 * base, so notes dilute each other but not iteratively — is the one every
 * comparable tool uses. It is right to a fraction of a point and it is not a
 * legal document. The page says so.
 */

export type SafeKind = 'post' | 'pre';

export interface Safe {
  amount: number;
  /** Valuation cap. Zero means uncapped. */
  cap: number;
  /** Zero means no discount. */
  discountPercent: number;
  /**
   * `post` is the YC standard since 2018 and the default. Its percentage is
   * fixed at conversion, so a second post-money SAFE dilutes the founders
   * rather than the first one. A `pre` note dilutes the other notes too.
   */
  kind: SafeKind;
}

export interface DilutionInput {
  /** What you hold today, as a percentage of the pre-round cap table. */
  yourPercent: number;
  safes: Safe[];
  preMoney: number;
  raise: number;
  /** The option pool as a percentage of the company after the round. */
  poolPercent: number;
  /** Pre-money is the standard ask, and it dilutes existing holders only. */
  poolPre: boolean;
}

export type Party = 'you' | 'other-existing' | 'safes' | 'investor' | 'pool';

export interface Holding {
  who: Party;
  /** Percentage before the round. `null` where the party did not yet exist. */
  before: number | null;
  after: number;
}

export interface Dilution {
  yourBefore: number;
  yourAfter: number;
  /** Points, not percent. 60 to 48 is twelve points and a twenty percent fall. */
  pointsGiven: number;
  /**
   * Which of the three took how many of those points.
   *
   * Attributed in the order the round actually happens — SAFEs convert, then
   * the pool is carved, then the money lands — so each figure is the marginal
   * cost of that step and the three sum exactly to `pointsGiven`. Any other
   * split of three multiplicative effects needs a convention; this one at
   * least matches the chronology.
   */
  attribution: { safes: number; pool: number; investor: number };
  stack: Holding[];
}

function number(value: number): number {
  return Number.isFinite(value) ? value : 0;
}

/**
 * The valuation a note actually converts at.
 *
 * A cap and a discount together are not combined — the holder takes whichever
 * gives more shares, which is the lower valuation of the two. Taking the first
 * one listed, or averaging them, quietly shorts the investor.
 */
function conversionValuation(note: Safe, preMoney: number): number {
  const options: number[] = [];

  if (note.cap > 0) options.push(note.cap);
  if (note.discountPercent > 0) {
    options.push(preMoney * (1 - Math.min(99, note.discountPercent) / 100));
  }

  // Neither a cap nor a discount: early money at the round's own price.
  if (options.length === 0) options.push(preMoney);

  return Math.max(1, Math.min(...options));
}

export function dilute(raw: DilutionInput): Dilution {
  const preMoney = Math.max(0, number(raw.preMoney));
  const raise = Math.max(0, number(raw.raise));
  const post = preMoney + raise;

  const yourBefore = Math.min(100, Math.max(0, number(raw.yourPercent)));
  const notes = raw.safes.filter((note) => number(note.amount) > 0);

  // ── SAFEs convert, against the company as it stands before the new money.
  //
  // A post-money note's slice is fixed by its own cap, so several of them add
  // up and the founders absorb all of it. A pre-money note prices off the
  // existing base, which means the notes dilute each other as well.
  let postShare = 0;
  let preRatio = 0;

  for (const note of notes) {
    // With no round entered yet there is no price to discount against, so the
    // note's own cap stands in. It keeps the figure finite rather than right —
    // the page shows nothing until there is a round.
    const valuation = conversionValuation(note, preMoney || Math.max(1, number(note.cap)));
    const slice = number(note.amount) / valuation;

    if (note.kind === 'post') postShare += slice;
    else preRatio += slice;
  }

  postShare = Math.min(0.99, postShare);

  // What is left after the fixed post-money slices, shared between the existing
  // holders and the pre-money notes in the ratio their conversion prices set.
  const existingOfPreMoney = (1 - postShare) / (1 + preRatio);
  const safesOfPreMoney = 1 - existingOfPreMoney;

  // ── The pool and the money.
  const investorSlice = post > 0 ? raise / post : 0;
  const pool = Math.min(0.95, Math.max(0, number(raw.poolPercent) / 100));

  let poolSurvival: number;
  let investorSurvival: number;
  let poolFinal: number;
  let investorFinal: number;

  if (raw.poolPre) {
    // Carved out of the pre-money slice, so the investor's percentage is
    // untouched and the whole cost lands on everybody already there. This is
    // the shuffle, and it is what a term sheet asks for.
    const room = Math.max(0, 1 - investorSlice);
    poolSurvival = room > 0 ? Math.max(0, 1 - pool / room) : 0;
    investorSurvival = 1 - investorSlice;
    poolFinal = Math.min(pool, room) * 100;
    investorFinal = investorSlice * 100;
  } else {
    // Created after the round, so it dilutes everyone including the investor.
    investorSurvival = 1 - investorSlice;
    poolSurvival = 1 - pool;
    poolFinal = pool * 100;
    investorFinal = investorSlice * (1 - pool) * 100;
  }

  // ── Attribution, in the order the round happens.
  const afterSafes = yourBefore * existingOfPreMoney;
  const afterPool = raw.poolPre ? afterSafes * poolSurvival : afterSafes;
  const afterMoney = afterPool * investorSurvival;
  const yourAfter = raw.poolPre ? afterMoney : afterMoney * poolSurvival;

  const attribution = raw.poolPre
    ? {
        safes: yourBefore - afterSafes,
        pool: afterSafes - afterPool,
        investor: afterPool - afterMoney,
      }
    : {
        safes: yourBefore - afterSafes,
        investor: afterSafes - afterMoney,
        pool: afterMoney - yourAfter,
      };

  // Everybody in the pre-money bucket meets the same two factors, in whichever
  // order the pool lands — the product is identical either way, which is why
  // one expression serves both cases and the branch that was here was a
  // ternary whose two sides agreed.
  const survival = poolSurvival * investorSurvival;
  const othersBefore = 100 - yourBefore;

  return {
    yourBefore,
    yourAfter,
    pointsGiven: yourBefore - yourAfter,
    attribution,
    stack: [
      { who: 'you', before: yourBefore, after: yourAfter },
      { who: 'other-existing', before: othersBefore, after: othersBefore * existingOfPreMoney * survival },
      { who: 'safes', before: null, after: safesOfPreMoney * survival * 100 },
      { who: 'pool', before: null, after: poolFinal },
      { who: 'investor', before: null, after: investorFinal },
    ],
  };
}
