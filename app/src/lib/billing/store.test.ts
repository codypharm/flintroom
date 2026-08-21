import { type Store, type Sellable, unconfiguredStore } from './store';

/**
 * The seam that lets the buy screen exist before a store account does.
 *
 * `CLAUDE.md` already makes this call twice — the voice provider sits behind an
 * interface so Gemini Live can replace ElevenLabs, and object storage sits
 * behind one so the contract is the presigned URL rather than a vendor SDK.
 * This is the same decision for the same reason, plus one specific to billing:
 * neither Google nor Apple lets a product identifier be reused once created, so
 * the names are worth deciding deliberately rather than under the pressure of
 * an unbuilt screen.
 *
 * **The screen never names a product.** RevenueCat's offerings exist precisely
 * so an app renders what the store returns; every price, title and duration on
 * screen comes from `Sellable`. That is what makes it possible to build all of
 * this today and fill in real prices later without touching the screen — and it
 * is also the only way the app cannot disagree with the till.
 */

it('sells nothing at all until a store is configured', async () => {
  // Not an empty list by accident — the whole point is that a build with no
  // store account cannot show a price, because any price it showed would be
  // invented. §4.4's figures are OUR pricing intent; the store is the authority
  // on what a person is actually charged, and the two are allowed to differ
  // until somebody reconciles them in a console.
  expect(await unconfiguredStore().sells()).toEqual([]);
});

it('refuses to sell rather than pretending it did', async () => {
  // The dangerous failure is a stub that resolves. A screen would clear its
  // spinner, show a receipt, and wait for minutes that no webhook will ever
  // grant — a user who believes they paid and did not.
  await expect(
    unconfiguredStore().buy({
      id: 'topup_20',
      title: 'Quick top-up',
      price: '$9.00',
      kind: 'topup',
    }),
  ).rejects.toThrow(/not configured/i);
});

it('is a Store, so nothing downstream can tell it from the real one', () => {
  // The type assertion is the test. If `unconfiguredStore` ever drifts from the
  // interface, every screen built against `Store` breaks at the point where the
  // real implementation lands — which is the worst possible moment for it.
  const store: Store = unconfiguredStore();
  const sellable: Sellable = {
    id: 'pro_monthly',
    title: 'Pro',
    price: '$59.00',
    kind: 'plan',
  };

  expect(typeof store.sells).toBe('function');
  expect(sellable.kind).toBe('plan');
});
