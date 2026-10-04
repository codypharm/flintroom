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
 * Two minutes in total. It was thirty seconds, reasoned rather than measured,
 * until 2026-10-04: an iOS sandbox top-up reached the webhook about 80 seconds
 * after it was bought, one second after that window closed, and the screen had
 * stopped looking. One observation, from sandbox, so this is a floor rather
 * than a distribution. A read every three seconds for two minutes is forty
 * small requests, which is cheap next to a buyer who thinks they paid for
 * nothing.
 *
 * The honest source is production — `ledger_entries` records when a top-up was
 * granted and the store records when it was bought, so the real gap is
 * recoverable later rather than guessable now.
 */
export const SETTLE_ATTEMPTS = 40;
export const SETTLE_GAP_MS = 3000;

export interface Settling {
  /** Injected so a test does not spend two minutes proving it waits. */
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

/**
 * How long the store gets to answer before the screen stops waiting on it.
 *
 * Set from one observation, not a distribution: on 2026-10-02 an iOS sandbox
 * top-up never answered at all, and the minutes landed only after a relaunch.
 * Twenty seconds is past any sheet a person is still looking at and short
 * enough that a frozen screen is never what they are left with.
 */
export const BUY_PATIENCE_MS = 20_000;

/**
 * Whether the store answered within `ms`.
 *
 * True when it did, false when it is still thinking, and its own refusal when
 * it refused in time, so a closed sheet still reads as a closed sheet. It does
 * not cancel anything: a purchase that answers late carries on, and the
 * screen, by then polling the server, sees its minutes arrive the same way.
 *
 * A refusal after `ms` is swallowed. The screen is no longer listening to the
 * store by then, and an unhandled rejection would draw an error over a
 * purchase that may have gone through.
 */
export async function answersWithin(
  answer: Promise<unknown>,
  ms: number,
  pause: (ms: number) => Promise<void> = wait,
): Promise<boolean> {
  let listening = true;
  const answered = answer.then(
    () => true,
    (thrown: unknown) => {
      if (listening) throw thrown;
      return false;
    },
  );
  const gaveUp = pause(ms).then(() => false);

  try {
    return await Promise.race([answered, gaveUp]);
  } finally {
    listening = false;
    // A late refusal now resolves to false instead of rejecting, but the
    // promise still needs a handler for the case where it rejected first.
    answered.catch(() => undefined);
  }
}

const wait = (ms: number) => new Promise<void>((done) => setTimeout(done, ms));
