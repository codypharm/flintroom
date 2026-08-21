/**
 * Waiting for a purchase to become minutes.
 *
 * **A purchase is three moments, and only the first happens on the phone.** The
 * store takes the money, RevenueCat calls our webhook, `grant_topup` moves the
 * balance. The middle step is a hop between two companies, and it is the reason
 * a screen must not show new minutes the instant `Store.buy()` resolves — it
 * would be stating a number the server has not agreed to, and it would be wrong
 * for however long that hop takes.
 *
 * So the screen waits here instead. In `lib/` rather than in the route because
 * routes carry no tests by convention (`CLAUDE.md` → Frontend) and this is the
 * part with behaviour worth pinning.
 *
 * **It gives up, and that is a feature.** A webhook that never lands is a real
 * outcome — a store outage, a rejected signature, a purchase that failed after
 * the sheet closed — and a screen that waited forever would spin until the app
 * was killed, having told somebody their money is somewhere.
 */

/**
 * How many times to ask before giving up, and how long between.
 *
 * Roughly thirty seconds in total. Reasoned rather than measured, and worth
 * revisiting against a real store: RevenueCat delivers most webhooks in
 * seconds, but "most" is doing work in that sentence and neither number here
 * comes from an observed distribution.
 *
 * The honest source is production — `ledger_entries` records when a top-up was
 * granted and the store records when it was bought, so the real gap is
 * recoverable later rather than guessable now.
 */
export const SETTLE_ATTEMPTS = 10;
export const SETTLE_GAP_MS = 3000;

export interface Settling {
  /** Injected so a test does not spend thirty seconds proving it waits. */
  pause?(ms: number): Promise<void>;
  attempts?: number;
  gapMs?: number;
}

/**
 * Poll until the balance is larger than it was, or until we stop asking.
 *
 * @param read what the account holds now, in whole minutes
 * @param was what it held before the purchase
 * @returns whether it moved
 */
export async function settles(
  read: () => Promise<number>,
  was: number,
  { pause = wait, attempts = SETTLE_ATTEMPTS, gapMs = SETTLE_GAP_MS }: Settling = {},
): Promise<boolean> {
  for (let asked = 0; asked < attempts; asked += 1) {
    // Waits first, always. The caller has just been told the store is
    // satisfied; reading immediately asks the server a question it cannot yet
    // have the answer to and burns an attempt on a certainty.
    await pause(gapMs);

    try {
      // **Larger, not different.** A tick from a room running on another device
      // can land mid-wait, and treating any change as arrival would stop early
      // and present a *smaller* number as the new balance.
      if ((await read()) > was) return true;
    } catch {
      // A failed read during the wait is ordinary — the phone changed networks.
      // Abandoning here would report a purchase as lost over an unrelated blip,
      // which is the worst thing this function could get wrong.
    }
  }

  return false;
}

const wait = (ms: number) => new Promise<void>((done) => setTimeout(done, ms));
