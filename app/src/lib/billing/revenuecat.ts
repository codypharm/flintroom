/**
 * The real store — RevenueCat behind the `Store` seam.
 *
 * The other half of #96. Everything the seam promised holds here: the app
 * still never names a product, prices arrive formatted in the buyer's
 * currency, and the join to what we grant travels as `grants` — our names,
 * configured in the RevenueCat console as the six package identifiers this
 * table repeats. Change one there and here together or the shop half-closes.
 *
 * **The SDK is a thunk, not an import.** The native module cannot load under
 * Jest at all, and a binary built before the module existed would die at
 * require time if this file imported it at the top. Resolved lazily, the
 * worst a stale build can do is throw inside `sells()` — which the buy screen
 * already treats as a shop with nothing on the shelves.
 */

import type { Sellable, Store } from './store';

export interface PackageLike {
  identifier: string;
  product: { title: string; priceString: string };
}

/** The corner of react-native-purchases this store stands on. */
export interface PurchasesLike {
  configure(configuration: { apiKey: string }): void;
  logIn(appUserID: string): Promise<unknown>;
  getOfferings(): Promise<{ current: { availablePackages: PackageLike[] } | null }>;
  purchasePackage(aPackage: PackageLike): Promise<unknown>;
  restorePurchases(): Promise<unknown>;
}

/**
 * Which of ours each console package sells.
 *
 * `grants` speaks the names `/v1/plans` and `/v1/packs` publish — a rung's or
 * a pack's — because that is the only join the screen performs. `pro_annual`
 * is deliberately off the ladder (`docs/billing-setup.md`: a sideways move,
 * not a rung), so its entry matches nothing today and renders nowhere; it is
 * kept so the package lights up the day a rung exists rather than being
 * silently dropped as unknown.
 */
const SOLD: Record<string, Pick<Sellable, 'kind' | 'grants'>> = {
  starter_monthly: { kind: 'plan', grants: 'starter' },
  pro_monthly: { kind: 'plan', grants: 'pro' },
  pro_annual: { kind: 'plan', grants: 'pro_annual' },
  topup_20: { kind: 'topup', grants: 'topup_20' },
  topup_90: { kind: 'topup', grants: 'topup_90' },
  topup_300: { kind: 'topup', grants: 'topup_300' },
};

export interface RevenueCatOptions {
  /** The public SDK key — an identifier, not a secret; it ships in the bundle. */
  apiKey: string;
  /**
   * Whose purchases these are. Sent to RevenueCat as the `app_user_id` the
   * webhook attributes by — an anonymous purchase would be money the backend
   * cannot grant, so identification precedes every store call.
   */
  userId(): Promise<string>;
  /** Injected in tests; defaults to the native module, resolved lazily. */
  purchases?(): PurchasesLike;
}

export function revenueCatStore({
  apiKey,
  userId,
  purchases = native,
}: RevenueCatOptions): Store {
  let configured = false;
  let identified: string | null = null;
  let shelf = new Map<string, PackageLike>();

  // Configure once, then keep the SDK's idea of who is buying in step with
  // ours — a signed-out-and-back-in-as-someone-else device must not attribute
  // the next purchase to the previous account.
  const ready = async (): Promise<PurchasesLike> => {
    const sdk = purchases();
    if (!configured) {
      sdk.configure({ apiKey });
      configured = true;
    }
    const who = await userId();
    if (who !== identified) {
      await sdk.logIn(who);
      identified = who;
    }
    return sdk;
  };

  const stock = async (sdk: PurchasesLike): Promise<PackageLike[]> => {
    const offered = (await sdk.getOfferings()).current?.availablePackages ?? [];
    shelf = new Map(offered.map((one) => [one.identifier, one]));
    return offered;
  };

  return {
    async sells() {
      const offered = await stock(await ready());

      // Unknown identifiers are dropped, not guessed at: a package added to
      // the console after this build shipped is not an offer it can honestly
      // describe, and §4.5's layout needs a `kind` it cannot invent.
      return offered.flatMap((one) => {
        const ours = SOLD[one.identifier];
        if (!ours) return [];
        return [
          {
            id: one.identifier,
            title: one.product.title,
            price: one.product.priceString,
            ...ours,
          },
        ];
      });
    },

    async buy(what) {
      const sdk = await ready();

      // The shelf is a convenience, not the authority — a Sellable held
      // across a console refresh deserves one more look before a refusal.
      const found = shelf.get(what.id) ?? (await stock(sdk)).find((one) => one.identifier === what.id);
      if (!found) {
        throw new Error(`"${what.id}" is no longer offered — the console moved under this screen`);
      }

      await sdk.purchasePackage(found);
    },

    async restore() {
      await (await ready()).restorePurchases();
    },
  };
}

/**
 * The real module, reached only when a method runs. A build without the
 * native half throws here, inside a call the screens already guard, instead
 * of at import time where nothing does.
 */
function native(): PurchasesLike {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  return (require('react-native-purchases') as { default: PurchasesLike }).default;
}
