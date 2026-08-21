import { fireEvent, render, screen, within } from '@testing-library/react-native';

import type { Plan } from '../../lib/api/purchaseApi';
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

const PLANS: Plan[] = [
  {
    name: 'free', title: 'Free', minutes: 15, renews: false, seats: 3,
    retentionDays: 30, maxUploadMb: 10, mayAuthor: false,
    unmeteredCoaching: true, current: true,
  },
  {
    name: 'starter', title: 'Starter', minutes: 90, renews: true, seats: 4,
    retentionDays: 90, maxUploadMb: 25, mayAuthor: false,
    unmeteredCoaching: true, current: false,
  },
  {
    name: 'pro', title: 'Pro', minutes: 180, renews: true, seats: 5,
    retentionDays: 365, maxUploadMb: 100, mayAuthor: true,
    unmeteredCoaching: true, current: false,
  },
];

async function setup(overrides: Partial<MoreMinutesProps> = {}) {
  const props: MoreMinutesProps = {
    holding: 12,
    options: { upgradeFirst: false, nextTier: 'pro' },
    sells: [PACK, PLAN],
    plans: PLANS,
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
  await setup({
    options: { upgradeFirst: true, nextTier: 'pro' },
    sells: [PACK, { ...PLAN, tier: 'pro' }],
  });

  // The pack is still there. Which is *first* is asserted below, on the tree
  // order, because that is what "primary" means on a scrolling screen.
  expect(screen.getByText('Quick top-up')).toBeOnTheScreen();
  expect(screen.getByText('Pro')).toBeOnTheScreen();
});

/** What the screen puts first, read off the tree rather than off intent. */
const leadsWith = () =>
  screen.getAllByText(/Quick top-up|Starter/)[0].props.children as string;

it('puts the pack first on a first purchase', async () => {
  // §4.5 point 1. Somebody out of minutes the night before a board readout
  // needs twenty minutes, not a subscription — and the ordering IS the rule, so
  // it is asserted on position rather than on presence.
  await setup({ options: { upgradeFirst: false, nextTier: 'pro' }, sells: [PACK] });

  expect(leadsWith()).toMatch(/Quick top-up/);
});

it('puts the plans first on a repeat', async () => {
  // §4.5 point 2, and the only screen in the app whose hierarchy changes per
  // user. Separate from the test above rather than one that unmounts and
  // re-renders: `screen` keeps pointing at the torn-down tree, and every test
  // after it in the file then reads from nothing.
  await setup({ options: { upgradeFirst: true, nextTier: 'pro' }, sells: [PACK] });

  expect(leadsWith()).toMatch(/Starter/);
});

it('pushes nothing when there is no rung above', async () => {
  // A Pro subscriber has bought every rung there is — `pro_annual` is the same
  // capability on another period and `teams` has a smaller upload cap — so the
  // server answers `next_tier: null`.
  //
  // The plans stay on screen, because a pricing screen that shows nothing to
  // somebody at the top is a screen that cannot answer "what am I paying for".
  // What goes is the *push*: nothing is given the brand ground, and no card
  // grows a buy button, because there is nothing above them to sell.
  // On Pro, so nothing published is above them — which is what makes
  // `nextTier: null` coherent. The earlier version of this test left the
  // account on Free beside a null next rung, a combination that cannot happen.
  await setup({
    plans: PLANS.map((plan) => ({ ...plan, current: plan.name === 'pro' })),
    options: { upgradeFirst: false, nextTier: null },
    sells: [PACK, { ...PLAN, tier: 'pro' }],
  });

  expect(screen.getByText('Pro')).toBeOnTheScreen();
  expect(screen.queryByText(/^Get Pro$/)).toBeNull();
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

/**
 * #95 — the screen showed one sentence because I bound the plans to the store.
 *
 * The architect's verdict was "where are the plans and the likes". Only the
 * PRICE is the store's; what a plan gets you lives in `tiers.py` and needed no
 * offering to be true. These tests are what stop it being re-tied.
 */
describe('what a plan gets you', () => {
  it('describes every plan with no store configured at all', async () => {
    // The state the architect actually saw: no offering, so nothing to price.
    // A card that says what you get and cannot say the price is a real screen;
    // a sentence apologising for a build is not.
    await setup({ sells: [] });

    expect(screen.getByText('Starter')).toBeOnTheScreen();
    expect(screen.getByText('Pro')).toBeOnTheScreen();
  });

  it('leads with the largest honest unit rather than a raw figure', async () => {
    // §4.6: "'3 hours of executive-level interrogation every month' reads
    // generously. '15 credits' reads rationed. Identical product."
    await setup({ sells: [] });

    expect(screen.getByText(/3 hours a month/i)).toBeOnTheScreen();
    expect(screen.getByText(/90 minutes a month/i)).toBeOnTheScreen();
  });

  it('never calls the free tier monthly, because its minutes never come back', async () => {
    // Fifteen minutes for LIFE. Rendered as "a month" it would describe a more
    // generous plan than the one that exists — a promise the ledger refuses.
    await setup({ sells: [] });

    expect(screen.getByText(/15 minutes to start/i)).toBeOnTheScreen();
  });

  it('says what is unlimited on every card, not in a footnote', async () => {
    // §4.6 asks for this "at the top of every tier card". It is the genuine
    // differentiator — §4.1's metering boundary made real — and burying it
    // sells the product as minutes rather than as the thing minutes buy.
    await setup({ sells: [] });

    expect(screen.getAllByText(/unlimited coaching/i)).toHaveLength(PLANS.length);
  });

  it('marks the plan somebody is on instead of selling it back to them', async () => {
    await setup({ sells: [] });

    expect(screen.getByText(/your plan/i)).toBeOnTheScreen();
  });

  it('takes the price from the store and never from itself', async () => {
    // §4.4's table is our pricing *intent*. What somebody is charged is the
    // console's, in their currency. A screen holding its own states one number
    // and charges another.
    await setup({ sells: [{ ...PLAN, tier: 'pro', price: '€55,00' }] });

    expect(screen.getByText('€55,00')).toBeOnTheScreen();
  });
});
