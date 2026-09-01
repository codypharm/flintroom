/**
 * What the app can be sold, and by whom — behind an interface.
 *
 * The same call `CLAUDE.md` already makes twice. The voice provider sits behind
 * one so Gemini Live can replace ElevenLabs if latency or cost fails to hold,
 * and object storage sits behind one so *"the contract is the presigned URL,
 * not the vendor SDK"*. RevenueCat is the locked billing choice; this is what
 * keeps that choice from reaching every screen that mentions money.
 *
 * **The app never names a product.** Every price, title and duration on screen
 * comes from a `Sellable` the store handed over. RevenueCat's offerings exist
 * for exactly this, and two things follow from using them properly:
 *
 * 1. **The screen cannot disagree with the till.** `Product.md` §4.4 lists our
 *    pricing *intent*; what somebody is actually charged is whatever is in the
 *    console, in their currency, after whatever regional adjustment the store
 *    applies. An app rendering our constants would state one price and charge
 *    another, and would go stale the first time a price moved.
 * 2. **The identifiers can be named later.** Neither Google nor Apple lets a
 *    product identifier be reused once created — `docs/billing-setup.md` says
 *    so — which makes naming them a decision worth taking deliberately. Because
 *    nothing here hardcodes one, the whole flow can be built first and the
 *    console filled in afterwards.
 *
 * @see docs/billing-setup.md for the console work this is waiting on.
 */

/**
 * One thing a person can buy, as the store describes it.
 *
 * Deliberately thin. Anything richer — minutes granted, per-minute rate, margin
 * — is either the server's business or ours, and putting it here would invite a
 * screen to do arithmetic on a price it does not own.
 */
export interface Sellable {
  /** The store's own identifier. Passed back to buy; never parsed, never shown. */
  id: string;

  /** What the store calls it, in the store's words. */
  title: string;

  /**
   * Already formatted, already localised, already in their currency.
   *
   * A string rather than a number and a currency code, because formatting money
   * correctly is the store's job and doing it twice is how an app shows
   * "$9.00" to somebody the till will charge €8,49.
   */
  price: string;

  /**
   * Which of §4.5's two controls this belongs under.
   *
   * The rule is about ordering two *kinds* of purchase — a pack of minutes
   * against a monthly plan — so the kind has to survive the trip from the store
   * or the screen cannot lay itself out.
   */
  kind: 'topup' | 'plan';

  /**
   * Which of our products this sells — a rung's `name`, or a pack's.
   *
   * The join between what the store charges and what we grant, and it is
   * carried explicitly because it cannot be inferred: the product identifiers
   * belong to the console and neither store lets one be renamed once created,
   * so `id` is theirs and this is ours.
   *
   * `/v1/plans` and `/v1/packs` are the authority on what each *is*; this only
   * says which one a given store product buys. Absent on a product that maps to
   * neither, which is a misconfigured console rather than a state to render.
   */
  grants?: string;
}

export interface Store {
  /**
   * Everything on offer, or nothing at all.
   *
   * An empty list is a legitimate answer rather than an error: a build with no
   * store account has nothing to sell, and the screen has to be able to say so
   * plainly instead of failing.
   */
  sells(): Promise<Sellable[]>;

  /**
   * Take the money. Resolves when the *store* is satisfied, never when we are.
   *
   * The distinction matters and the screen has to respect it: the purchase
   * completes on the device, then RevenueCat calls our webhook, then
   * `grant_topup` moves the balance. Those are three separate moments, and the
   * one in the middle can be slow. A screen that shows new minutes the instant
   * this resolves is showing a number the server has not agreed to yet.
   */
  buy(what: Sellable): Promise<void>;

  /**
   * Re-attach purchases already made on this account.
   *
   * An App Store review requirement rather than a nicety, and the case it
   * serves is real: somebody who reinstalls, or signs in on a second device,
   * has paid and can see nothing for it.
   */
  restore(): Promise<void>;
}

/**
 * What a build with no store account has: nothing to sell, and no pretence.
 *
 * **It refuses rather than resolving**, and that is the whole design. A stub
 * that resolved would let a screen clear its spinner, show a receipt and wait
 * for minutes that no webhook will ever grant — a person who believes they paid
 * and did not. Failing loudly is the only honest behaviour for a shop with no
 * till, and it is what keeps this from being shippable by accident.
 */
export function unconfiguredStore(): Store {
  const refuse = async (): Promise<never> => {
    throw new Error('the store is not configured; see docs/billing-setup.md');
  };

  return {
    sells: async () => [],
    buy: refuse,
    restore: refuse,
  };
}
