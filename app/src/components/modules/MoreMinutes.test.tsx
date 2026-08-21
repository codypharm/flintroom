import { fireEvent, render, screen, within } from '@testing-library/react-native';

import type { Sellable } from '../../lib/billing/store';
import { MoreMinutes, type MoreMinutesProps } from './MoreMinutes';

/**
 * Buying more time in the room.
 *
 * These tests are about `Product.md` §4.5 and §4.6 rather than about layout.
 * What must not drift: which control leads and why, that a top-up is never
 * gated behind an upgrade, that no price is ever ours, and that a purchase is
 * not reported as minutes until the server agrees it is.
 *
 * `design-guide/billing_tokens/` is the mockup for this screen and every
 * content decision in it is retired — tokens rather than minutes, "4 / 10
 * remaining" which is precisely the depleting counter §4.6 forbids, weekly
 * resets against CLAUDE.md's locked monthly, custom URL scraping which was cut
 * for right-of-publicity reasons, and $19/mo against a real $59. Its hierarchy
 * is also backwards: it leads with plans and buries the pack at the bottom as a
 * "Booster Pack", which is the opposite of §4.5 point 1.
 */

const PACK: Sellable = {
  id: 'topup_20',
  title: 'Quick top-up',
  price: '$9.00',
  kind: 'topup',
};

const PLAN: Sellable = {
  id: 'pro_monthly',
  title: 'Pro',
  price: '$59.00',
  kind: 'plan',
};

async function setup(overrides: Partial<MoreMinutesProps> = {}) {
  const props: MoreMinutesProps = {
    holding: 12,
    options: { upgradeFirst: false, nextTier: 'pro' },
    sells: [PACK, PLAN],
    onBuy: jest.fn(),
    onRestore: jest.fn(),
    state: 'idle',
    ...overrides,
  };
  await render(<MoreMinutes {...props} />);
  return props;
}

it('leads with the pack the first time, and says the minutes are kept', async () => {
  // §4.5 point 1. Somebody out of minutes the night before a board readout
  // needs twenty minutes, not a subscription — a screen that leads with a
  // monthly plan has misread the moment it is being read in.
  //
  // The promise beside it is the credit itself: "The minutes are the credit"
  // (point 3), which the ledger keeps by putting top-ups in their own bucket.
  await setup({ options: { upgradeFirst: false, nextTier: 'pro' } });

  const offered = screen.getAllByTestId('sellable');
  expect(within(offered[0]).getByText('Quick top-up')).toBeOnTheScreen();
  expect(screen.getByText(/stay yours/i)).toBeOnTheScreen();
});

it('leads with the plan on a repeat, and still sells the pack', async () => {
  // §4.5 point 2 makes the upgrade primary. Point 4 forbids gating: "Never gate
  // the top-up behind the upgrade prompt. One tap to decline, always." So the
  // order changes and the pack stays purchasable — a screen that hid it would
  // be the farming the whole rule exists to prevent.
  await setup({ options: { upgradeFirst: true, nextTier: 'pro' } });

  const offered = screen.getAllByTestId('sellable');
  expect(within(offered[0]).getByText('Pro')).toBeOnTheScreen();
  expect(screen.getByText('Quick top-up')).toBeOnTheScreen();
});

it('offers no plan when there is no rung above', async () => {
  // A Pro subscriber has bought every rung there is. `pro_annual` is the same
  // capability on another period and `teams` has a smaller upload cap, so the
  // server answers `next_tier: null` — and showing a plan anyway would take
  // money for no more room.
  await setup({ options: { upgradeFirst: false, nextTier: null }, sells: [PACK, PLAN] });

  expect(screen.queryByText('Pro')).toBeNull();
  expect(screen.getByText('Quick top-up')).toBeOnTheScreen();
});

it('says what is held plainly, never as a fraction of anything', async () => {
  // §4.6: "Never display a depleting counter. '48 minutes available' not '2 of
  // 5 credits left'. Depletion framing makes users ration, and rationing users
  // churn." The mockup this replaces led with "4 / 10 remaining".
  await setup({ holding: 12 });

  expect(screen.getByText(/12 minutes/)).toBeOnTheScreen();
  expect(screen.queryByText(/\d+\s*\/\s*\d+/)).toBeNull();
});

it('prices nothing itself', async () => {
  // Every figure on screen came from the store. §4.4's numbers are our pricing
  // *intent*; what somebody is charged is whatever the console says, in their
  // currency, after whatever regional adjustment applies. A screen holding its
  // own prices states one number and charges another.
  await setup({ sells: [{ ...PACK, price: '€8,49' }] });

  expect(screen.getByText('€8,49')).toBeOnTheScreen();
});

it('says plainly when there is nothing to sell rather than spinning', async () => {
  // An empty list is a real answer — a build with no store account, or a store
  // that answered with nothing. Both must read as a shop that is shut, not as a
  // screen still loading, or somebody waits forever for a list that has arrived.
  await setup({ sells: [] });

  expect(screen.getByText(/not available/i)).toBeOnTheScreen();
});

it('hands the store back exactly what was tapped', async () => {
  const props = await setup();

  fireEvent.press(screen.getByText('Quick top-up'));

  expect(props.onBuy).toHaveBeenCalledWith(PACK);
});

it('does not claim the minutes the moment the store is satisfied', async () => {
  // Three moments, not one: the purchase completes on the device, RevenueCat
  // calls our webhook, `grant_topup` moves the balance. A screen that showed
  // new minutes when `buy()` resolved would be stating a number the server has
  // not agreed to — and would be wrong for however long the middle step takes.
  await setup({ state: 'waiting', holding: 12 });

  expect(screen.getByText(/12 minutes/)).toBeOnTheScreen();
  expect(screen.getByText(/adding them now/i)).toBeOnTheScreen();
});

it('says a purchase failed without saying anything about money', async () => {
  // We cannot know whether they were charged — the store owns that, and a
  // failure here covers a declined card, a cancelled sheet and a dropped
  // connection alike. "Nothing was charged" would be a claim we cannot make.
  await setup({ state: 'failed' });

  expect(screen.getByText(/did not go through/i)).toBeOnTheScreen();
});

it('can re-attach a purchase made somewhere else', async () => {
  // An App Store review requirement, and a real case: somebody who reinstalls
  // or signs in on a second device has paid and can see nothing for it.
  const props = await setup();

  fireEvent.press(screen.getByText(/restore/i));

  expect(props.onRestore).toHaveBeenCalled();
});
