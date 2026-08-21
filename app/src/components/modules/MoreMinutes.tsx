import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { PurchaseOptions } from '../../lib/api/purchaseApi';
import type { Sellable } from '../../lib/billing/store';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * Buying more time in the room.
 *
 * THESIS: this is not a paywall, and the difference is structural rather than
 * tonal. A paywall stands between somebody and the thing they came for. This
 * screen is reached deliberately, from Settings or from a room that would not
 * open, and it can always be left with the back gesture — which is what §4.5
 * point 4 means by *"one tap to decline, always"*. Nothing here is dismissible-
 * only-by-buying, and there is no modal.
 *
 * OWN-WORLD: the established Flintroom system, inherited whole. Warm off-white
 * ground, paper-white cards, burnt orange once, Hanken Grotesk, hairlines. No
 * value that `tokens.ts` does not carry.
 *
 * FORM: two stacked groups whose *order is the product rule*. §4.5 decides
 * which leads, and it is the only screen in the app whose hierarchy changes per
 * user — deliberately, because the rule is about catching somebody at the point
 * where repeat top-ups stop being good for them.
 *
 * WHAT THE MOCKUP CONTRIBUTED: density, and nothing else.
 * `design-guide/billing_tokens/` is fully retired — "Tokens", "4 / 10
 * remaining" (the depleting counter §4.6 forbids, as the first thing on the
 * screen), weekly resets against CLAUDE.md's locked monthly, "Custom URL
 * scraping" which is the scraping §3.1 cut, $19/mo against a real $59, and a
 * "Profile" tab this app no longer has. Its hierarchy is also inverted: plans
 * first, the pack last as a "Booster Pack", which is the opposite of point 1.
 *
 * ---
 *
 * **No price here is ours.** Every figure comes from `Sellable`, which comes
 * from the store. §4.4's table is our pricing *intent*; what somebody is
 * actually charged is whatever the console holds, in their currency, after
 * whatever regional adjustment applies. A screen carrying its own numbers would
 * state one price and charge another, and would go stale the first time one
 * moved.
 */

export interface MoreMinutesProps {
  /** Whole minutes held, or null while unknown. Never seconds — see §4.6. */
  holding: number | null;

  /**
   * Which control leads, from the server. Null while unknown.
   *
   * The rule and its rolling window live in `LedgerService.purchase_options`
   * so this screen cannot hold a second copy free to drift.
   */
  options: PurchaseOptions | null;

  /**
   * What the store will sell, or null while it has not answered.
   *
   * The empty array and null are different states and must stay so: nothing to
   * sell is a shop that is shut, and null is one that has not opened its door.
   * Collapsing them leaves somebody watching a spinner for a list that arrived.
   */
  sells: Sellable[] | null;

  onBuy: (what: Sellable) => void;
  onRestore: () => void;

  /**
   * Where a purchase has got to.
   *
   * `waiting` is the state most products get wrong. A purchase completes on the
   * device, then RevenueCat calls our webhook, then `grant_topup` moves the
   * balance — three moments, and the middle one can be slow. Showing new
   * minutes when the store is satisfied states a number the server has not
   * agreed to.
   */
  state: 'idle' | 'buying' | 'waiting' | 'failed';
}

export function MoreMinutes({
  holding,
  options,
  sells,
  onBuy,
  onRestore,
  state,
}: MoreMinutesProps) {
  const offered = ordered(sells, options);

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Text style={styles.title} accessibilityRole="header">
        More time in the room
      </Text>

      {/*
        What they hold, stated rather than counted down. §4.6: "'48 minutes
        available' not '2 of 5 credits left'. Depletion framing makes users
        ration, and rationing users churn." The retired mockup opened with
        "4 / 10 remaining", which is that framing as the first thing read.
      */}
      {holding !== null && (
        <Text style={styles.holding}>{`You have ${holding} minutes.`}</Text>
      )}

      {state === 'waiting' && (
        <Text style={styles.pending} accessibilityLiveRegion="polite">
          Thank you — adding them now. This can take a moment.
        </Text>
      )}

      {state === 'failed' && (
        <Text style={styles.wrong} accessibilityLiveRegion="polite">
          That did not go through. Your store will have the details.
        </Text>
      )}

      {sells === null ? null : offered.length === 0 ? (
        <Text style={styles.shut}>
          Buying more time is not available on this build yet.
        </Text>
      ) : (
        offered.map((what, at) => (
          <Buy
            key={what.id}
            what={what}
            lead={at === 0}
            busy={state === 'buying'}
            onBuy={onBuy}
          />
        ))
      )}

      {/*
        §4.5 point 1, and only on a first purchase — it is the answer to "am I
        wasting this if I subscribe later", and the answer is no because the
        ledger keeps top-up minutes in their own bucket forever. On a repeat the
        upgrade already leads and the sentence would read as a consolation.
      */}
      {options?.upgradeFirst === false && offered.length > 0 && (
        <Text style={styles.kept}>
          Buy time now or subscribe — either way, minutes you buy stay yours and
          never expire.
        </Text>
      )}

      <Pressable
        onPress={onRestore}
        accessibilityRole="button"
        style={({ pressed }) => [styles.restore, pressed && styles.pressed]}
      >
        <Text style={styles.restoreText}>Restore a previous purchase</Text>
      </Pressable>
    </ScrollView>
  );
}

/**
 * What to show, in the order §4.5 asks for.
 *
 * A plan is dropped entirely when there is no rung above rather than shown and
 * disabled: a Pro subscriber has bought every rung there is, and offering one
 * anyway takes money for no more room.
 *
 * The pack is never dropped. Point 4 is explicit, and the ordering below is the
 * only thing that changes between a first purchase and a repeat.
 */
function ordered(
  sells: Sellable[] | null,
  options: PurchaseOptions | null,
): Sellable[] {
  if (sells === null) return [];

  const buyable = sells.filter(
    (what) => what.kind === 'topup' || options?.nextTier != null,
  );

  return options?.upgradeFirst
    ? [...buyable].sort((a, b) => rank(b) - rank(a))
    : [...buyable].sort((a, b) => rank(a) - rank(b));
}

/** Top-ups sort first by default; `upgradeFirst` reverses it. */
const rank = (what: Sellable) => (what.kind === 'topup' ? 0 : 1);

function Buy({
  what,
  lead,
  busy,
  onBuy,
}: {
  what: Sellable;
  lead: boolean;
  busy: boolean;
  onBuy: (what: Sellable) => void;
}) {
  return (
    <Pressable
      testID="sellable"
      accessibilityRole="button"
      accessibilityLabel={`${what.title}, ${what.price}`}
      disabled={busy}
      onPress={() => onBuy(what)}
      style={({ pressed }) => [
        styles.card,
        // The lead control is the primary one, per §4.5 point 2. Weight and
        // ground, never the *presence* of the other — this is which is bigger,
        // not which exists.
        lead && styles.leading,
        pressed && styles.pressed,
        busy && styles.busy,
      ]}
    >
      <Text style={[styles.what, lead && styles.whatLeading]}>{what.title}</Text>
      <Text style={[styles.price, lead && styles.priceLeading]}>{what.price}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
  content: { padding: space.screen, paddingBottom: space.major, gap: space.snug },

  title: { ...type.headlineLg, color: color.onSurface },

  holding: {
    ...type.bodyLg,
    color: color.onSurfaceVariant,
    marginBottom: space.tight,
  },

  pending: { ...type.bodySm, color: color.onSurfaceVariant },
  wrong: { ...type.bodySm, color: color.danger },
  shut: { ...type.bodySm, color: color.onSurfaceVariant },

  card: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: color.card,
    borderRadius: radius.card,
    padding: space.base,
    minHeight: 44,
  },
  /** The primary control: brand ground, used once, per §9. */
  leading: { backgroundColor: color.primary },
  pressed: { opacity: 0.7 },
  busy: { opacity: 0.5 },

  what: { ...type.labelLg, color: color.onSurface },
  whatLeading: { color: color.onPrimary },
  price: { ...type.bodyLg, color: color.onSurfaceVariant },
  priceLeading: { color: color.onPrimary },

  kept: { ...type.bodySm, color: color.onSurfaceVariant, paddingTop: space.tight },

  restore: { paddingVertical: space.base, minHeight: 44, justifyContent: 'center' },
  restoreText: { ...type.bodySm, color: color.onSurfaceVariant },
});
