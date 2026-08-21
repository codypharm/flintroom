import { SignedOut } from '../auth/session';

/**
 * Which control the buy screen leads with, and what there is to lead with.
 *
 * `Product.md` §4.5's Credit-Toward-Upgrade Rule, answered by the server. The
 * rule — *"on the second top-up in any rolling 30-day window, make the upgrade
 * the default option and the top-up the secondary one"* — and its window are
 * business logic, and a client computing them from a raw count would be a
 * second implementation free to drift from the first.
 *
 * **No count comes across, deliberately.** `balanceApi` refuses raw seconds for
 * the reason §4.6 gives — a number that only ever falls invites a display that
 * makes people ration — and "you have topped up twice this month" is that
 * display in a different hat. Somebody who bought two packs knows they did.
 *
 * **Nothing here can withhold a top-up.** §4.5 point 4: *"Never gate the top-up
 * behind the upgrade prompt. One tap to decline, always."* This says which
 * control is larger; the type has no way to say either is unavailable.
 */

export interface PurchaseOptions {
  /**
   * Whether the upgrade is the primary control and the top-up the secondary.
   *
   * False on somebody's first purchase, and that is not a default — §4.5 point
   * 1 keeps the top-up primary the first time on purpose. A person out of
   * minutes the night before a board readout needs twenty minutes, not a
   * subscription, and a screen that leads with a monthly plan has misread them.
   */
  upgradeFirst: boolean;

  /**
   * The rung to offer, or null at the top of the ladder.
   *
   * **Null is an answer, never a loading state.** A Pro subscriber has bought
   * every rung there is, so there is nothing to steer them toward — a screen
   * that read null as "not yet known" would spin forever on exactly the
   * customers who pay most.
   */
  nextTier: string | null;
}

export interface PurchaseApi {
  options(): Promise<PurchaseOptions>;
}

export interface PurchaseApiOptions {
  baseUrl: string;
  accessToken(): Promise<string>;
  fetch?: typeof fetch;
}

export function createPurchaseApi({
  baseUrl,
  accessToken,
  fetch: fetcher = fetch,
}: PurchaseApiOptions): PurchaseApi {
  return {
    options: async () => {
      const response = await fetcher(`${baseUrl}/v1/purchase-options`, {
        headers: { Authorization: `Bearer ${await accessToken()}` },
      });

      if (response.status === 401) {
        throw new SignedOut('refused by /v1/purchase-options');
      }
      if (!response.ok) {
        throw new Error(`/v1/purchase-options failed with ${response.status}`);
      }

      const body = (await response.json()) as {
        upgrade_first: boolean;
        next_tier: string | null;
      };

      return { upgradeFirst: body.upgrade_first, nextTier: body.next_tier ?? null };
    },
  };
}
