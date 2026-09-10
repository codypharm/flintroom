import { SignedOut } from '../auth/session';
import { boundedFetch } from '../net/bounded';

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
  plans(): Promise<Plan[]>;
  packs(): Promise<Pack[]>;
}

export interface PurchaseApiOptions {
  baseUrl: string;
  accessToken(): Promise<string>;
  fetch?: typeof fetch;
}

export function createPurchaseApi({
  baseUrl,
  accessToken,
  fetch: fetcher = boundedFetch(),
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

    packs: async () => {
      const response = await fetcher(`${baseUrl}/v1/packs`, {
        headers: { Authorization: `Bearer ${await accessToken()}` },
      });

      if (response.status === 401) {
        throw new SignedOut('refused by /v1/packs');
      }
      if (!response.ok) {
        throw new Error(`/v1/packs failed with ${response.status}`);
      }

      return (await response.json()) as Pack[];
    },

    plans: async () => {
      const response = await fetcher(`${baseUrl}/v1/plans`, {
        headers: { Authorization: `Bearer ${await accessToken()}` },
      });

      if (response.status === 401) {
        throw new SignedOut('refused by /v1/plans');
      }
      if (!response.ok) {
        throw new Error(`/v1/plans failed with ${response.status}`);
      }

      return ((await response.json()) as PlanBody[]).map((plan) => ({
        name: plan.name,
        title: plan.title,
        minutes: plan.minutes,
        renews: plan.renews,
        seats: plan.seats,
        retentionDays: plan.retention_days,
        maxUploadMb: plan.max_upload_mb,
        mayAuthor: plan.may_author,
        unmeteredCoaching: plan.unmetered_coaching,
        current: plan.current,
      }));
    },
  };
}

interface PlanBody {
  name: string;
  title: string;
  minutes: number;
  renews: boolean;
  seats: number;
  retention_days: number;
  max_upload_mb: number;
  may_author: boolean;
  unmetered_coaching: boolean;
  current: boolean;
}

/**
 * One rung, as what it gets you.
 *
 * **No price, and that is the seam #95 got wrong the first time.** The store
 * owns what somebody is charged — in their currency, after regional adjustment,
 * changeable in a console without a release. We own what they get, and every
 * figure here already lived in `billing/tiers.py`.
 *
 * Read from the server rather than shipped in the app, on the argument the
 * upload limits already won: the tier table has one home, and a client holding
 * its own can offer a plan we retired.
 */
export interface Plan {
  /** The tier key — `free`, `starter`, `pro`. */
  name: string;
  title: string;
  /** Whole minutes of interrogation. */
  minutes: number;
  /**
   * Whether those minutes come back each month.
   *
   * False for the free tier, whose fifteen are for life — and a card reading
   * "15 minutes" beside "90 minutes a month" would be read as a smaller
   * monthly allowance, which is a more generous plan than the one that exists.
   */
  renews: boolean;
  seats: number;
  retentionDays: number;
  maxUploadMb: number;
  mayAuthor: boolean;
  /** Always true. §4.6 wants it on every card rather than in a footnote. */
  unmeteredCoaching: boolean;
  /** Whether the caller is on this plan. Nothing is marked for a tier off the ladder. */
  current: boolean;
}


/**
 * One top-up, by what it grants.
 *
 * Same seam as `Plan`: the minutes are ours and the price is the store's. The
 * packs were left store-driven when the plans were fixed, so a build with no
 * offering showed three real plan cards and no way at all to buy twenty
 * minutes — the same mistake one section over.
 *
 * The title is ours too. The store's is a marketing string, and §4.5's names
 * carry the *occasion* each pack is for, which is the reason the smallest one
 * "must feel small".
 */
export interface Pack {
  /** Our key. What a store product declares to say which pack it sells. */
  name: string;
  title: string;
  minutes: number;
}
