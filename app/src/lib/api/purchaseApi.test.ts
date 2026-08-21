import { createPurchaseApi } from './purchaseApi';

/**
 * Which control the buy screen leads with — `Product.md` §4.5.
 *
 * The rule and its window live on the server (`LedgerService.purchase_options`)
 * so that a client cannot hold a second copy of "a rolling thirty days" free to
 * drift from the first. This module only carries the answer across.
 */

function api(response: { status: number; json?: () => Promise<unknown> }) {
  const fetcher = jest.fn().mockResolvedValue({
    ok: response.status >= 200 && response.status < 300,
    status: response.status,
    json: response.json ?? (async () => ({})),
  });

  return {
    fetcher,
    purchases: createPurchaseApi({
      baseUrl: 'https://api.example',
      accessToken: async () => 'a-token',
      fetch: fetcher as unknown as typeof fetch,
    }),
  };
}

it('carries which control leads and what there is to lead with', async () => {
  const { purchases } = api({
    status: 200,
    json: async () => ({ upgrade_first: true, next_tier: 'pro' }),
  });

  expect(await purchases.options()).toEqual({ upgradeFirst: true, nextTier: 'pro' });
});

it('reads the top of the ladder as nothing to offer, not as a missing field', async () => {
  // `pro_annual` is the same capability on another billing period and `teams`
  // has a *smaller* upload cap, so neither is on the server's UPGRADE_LADDER. A
  // Pro subscriber buying a third pack genuinely has nowhere to be sent, and a
  // screen that treated null as "not loaded yet" would spin forever on them.
  const { purchases } = api({
    status: 200,
    json: async () => ({ upgrade_first: false, next_tier: null }),
  });

  expect(await purchases.options()).toEqual({ upgradeFirst: false, nextTier: null });
});
