import { PurchaseCancelled, revenueCatStore, type PackageLike, type PurchasesLike } from './revenuecat';

/**
 * The store seam's real half — RevenueCat behind the `Store` interface.
 *
 * The SDK arrives as an injected thunk because the native module cannot even
 * be imported under Jest, and that constraint is also the production shape: a
 * build whose binary lacks the module degrades to a shop that answers with
 * nothing rather than an app that dies at launch.
 */

const pkg = (identifier: string, title: string, priceString: string): PackageLike => ({
  identifier,
  product: { title, priceString },
});

const OFFERED: PackageLike[] = [
  pkg('starter_monthly', 'Starter', '$29.00'),
  pkg('pro_monthly', 'Pro', '$59.00'),
  pkg('pro_annual', 'Pro Annual', '$599.00'),
  pkg('topup_20', 'Quick Top-Up — 20 minutes', '$9.00'),
  pkg('topup_90', 'Demo-Day Pack — 90 minutes', '$35.00'),
  pkg('topup_300', 'Cohort Block — 300 minutes', '$99.00'),
];

function fakeSdk(available: PackageLike[] = OFFERED) {
  const sdk = {
    configure: jest.fn(),
    logIn: jest.fn().mockResolvedValue({}),
    getOfferings: jest
      .fn()
      .mockImplementation(async () => ({ current: { availablePackages: available } })),
    purchasePackage: jest.fn().mockResolvedValue({}),
    restorePurchases: jest.fn().mockResolvedValue({}),
  } satisfies PurchasesLike & Record<string, jest.Mock>;
  return sdk;
}

const storeWith = (sdk: PurchasesLike, userId = async () => 'user-1') =>
  revenueCatStore({ apiKey: 'goog_test', userId, purchases: () => sdk });

it('maps the offering into sellables the screen can join', async () => {
  const sdk = fakeSdk([...OFFERED, pkg('mystery_pack', 'Mystery', '$1.00')]);

  const sold = await storeWith(sdk).sells();

  // The join carried explicitly: `grants` speaks our names (a rung's, a
  // pack's), `id` stays the store's. The unknown package is dropped rather
  // than guessed at — a console addition the app predates is not an offer
  // this build can honestly describe.
  expect(sold.map((s) => [s.id, s.kind, s.grants])).toEqual([
    ['starter_monthly', 'plan', 'starter'],
    ['pro_monthly', 'plan', 'pro'],
    ['pro_annual', 'plan', 'pro_annual'],
    ['topup_20', 'topup', 'topup_20'],
    ['topup_90', 'topup', 'topup_90'],
    ['topup_300', 'topup', 'topup_300'],
  ]);
  expect(sold[0].title).toBe('Starter');
  expect(sold[0].price).toBe('$29.00');
});

it('configures once and identifies the buyer before selling anything', async () => {
  const sdk = fakeSdk();
  const store = storeWith(sdk);

  await store.sells();
  await store.sells();

  // app_user_id is our user_id — the webhook attributes every purchase by it,
  // so an anonymous purchase would be money we cannot grant.
  expect(sdk.configure).toHaveBeenCalledTimes(1);
  expect(sdk.configure).toHaveBeenCalledWith({ apiKey: 'goog_test' });
  expect(sdk.logIn).toHaveBeenCalledTimes(1);
  expect(sdk.logIn).toHaveBeenCalledWith('user-1');
  expect(sdk.logIn.mock.invocationCallOrder[0]).toBeLessThan(
    sdk.getOfferings.mock.invocationCallOrder[0],
  );
});

it('re-identifies when the account changes', async () => {
  const sdk = fakeSdk();
  let who = 'user-1';
  const store = storeWith(sdk, async () => who);

  await store.sells();
  who = 'user-2';
  await store.sells();

  expect(sdk.logIn.mock.calls).toEqual([['user-1'], ['user-2']]);
});

it('buys the exact package the sellable named', async () => {
  const sdk = fakeSdk();
  const store = storeWith(sdk);

  const sold = await store.sells();
  await store.buy(sold.find((s) => s.id === 'topup_90')!);

  expect(sdk.purchasePackage).toHaveBeenCalledTimes(1);
  const bought = sdk.purchasePackage.mock.calls[0][0] as PackageLike;
  expect(bought.identifier).toBe('topup_90');
});

it('looks again before refusing a package it has not seen', async () => {
  // The screen can hold a Sellable across a refresh of the console — the
  // cache is a convenience, not the authority, so one more look precedes any
  // refusal.
  const sdk = fakeSdk();
  const store = storeWith(sdk);

  await store.buy({
    id: 'topup_20',
    title: 'Quick Top-Up',
    price: '$9.00',
    kind: 'topup',
    grants: 'topup_20',
  });

  expect(sdk.getOfferings).toHaveBeenCalledTimes(1);
  expect(sdk.purchasePackage).toHaveBeenCalledTimes(1);
});

it('refuses a package the console no longer offers', async () => {
  const sdk = fakeSdk([]);

  await expect(
    storeWith(sdk).buy({
      id: 'topup_20',
      title: 'Quick Top-Up',
      price: '$9.00',
      kind: 'topup',
      grants: 'topup_20',
    }),
  ).rejects.toThrow(/no longer offered/);
  expect(sdk.purchasePackage).not.toHaveBeenCalled();
});

it('a cancelled sheet is a cancellation, never a failure', async () => {
  // #107 item 6. The SDK reports a deliberate cancel distinctly
  // (userCancelled on the rejection), and the screen needs the distinction:
  // "that did not work" over a sheet somebody chose to close reads as the
  // product failing, when nothing failed.
  const sdk = fakeSdk();
  sdk.purchasePackage.mockRejectedValue(
    Object.assign(new Error('Purchase was cancelled.'), { userCancelled: true }),
  );
  const store = storeWith(sdk);

  const sold = await store.sells();
  await expect(store.buy(sold[0])).rejects.toBeInstanceOf(PurchaseCancelled);
});

it('a genuine store failure stays a failure', async () => {
  const sdk = fakeSdk();
  sdk.purchasePackage.mockRejectedValue(new Error('card declined'));
  const store = storeWith(sdk);

  const sold = await store.sells();
  const refused = store.buy(sold[0]);
  await expect(refused).rejects.toThrow('card declined');
  await expect(refused).rejects.not.toBeInstanceOf(PurchaseCancelled);
});


it('restores through the store', async () => {
  const sdk = fakeSdk();

  await storeWith(sdk).restore();

  expect(sdk.restorePurchases).toHaveBeenCalledTimes(1);
});
