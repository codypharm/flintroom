import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { Pack, Plan, PurchaseOptions } from '../../lib/api/purchaseApi';
import type { Sellable } from '../../lib/billing/store';
import { color, radius, space, type } from '../../theme/tokens';
import { PlanCard } from './PlanCard';

/**
 * Buying more time in the room.
 *
 * THESIS: this is not a paywall. A paywall stands between somebody and the
 * thing they came for; this is reached deliberately, from Settings or from a
 * room that would not open, and it can always be left with the back gesture —
 * which is what §4.5 point 4 means by *"one tap to decline, always"*. Nothing
 * here is dismissible-only-by-buying, and there is no modal.
 *
 * **WHAT THIS GOT WRONG FIRST TIME, because it is the whole shape of the
 * screen.** Every card rendered from the store's `Sellable`, so with no
 * offering configured there was nothing to draw and the screen fell back to one
 * sentence. The architect's verdict was "where are the plans and the likes",
 * and it was right: the seam was in the wrong place.
 *
 * The store owns what somebody is **charged**. We own what they **get**. Every
 * figure on a plan card lived in `billing/tiers.py` the whole time and needed
 * no offering to be true, so the plans render with or without a store and the
 * price is the one thing that can be absent.
 *
 * ORDER IS THE PRODUCT RULE. §4.5 decides whether the pack or the plan leads,
 * so this is the only screen in the app whose hierarchy changes per user —
 * deliberately, because the rule exists to catch somebody at the point where
 * repeat top-ups stop being good for them.
 *
 * THREE GROUPS, AND THAT IS THE LAYOUT. The standing — what you hold, and any
 * reason buying might not work. The two offers, each named, in the order §4.5
 * chose. Then housekeeping, past a rule. What the screen used to be was one
 * flat column at a single interval, where the only labelled group was whichever
 * one happened to be the packs: flip the order and the screen led with three
 * unheaded cards. **Both offers are labelled now, so the ordering rule can
 * swap them without the reader losing the boundary.**
 *
 * WHAT THE MOCKUP CONTRIBUTED: density, and nothing else.
 * `design-guide/billing_tokens/` is fully retired — "Tokens", "4 / 10
 * remaining" (the depleting counter §4.6 forbids, as the first thing read),
 * weekly resets against CLAUDE.md's locked monthly, "Custom URL scraping" which
 * is the scraping §3.1 cut, $19/mo against a real $59, and a Profile tab this
 * app no longer has.
 */

export interface MoreMinutesProps {
  /** Whole minutes held, or null while unknown. Never seconds — see §4.6. */
  holding: number | null;

  /** Which control leads, from the server. Null while unknown. */
  options: PurchaseOptions | null;

  /**
   * What each rung gets you, from `/v1/plans`. Null while unknown.
   *
   * Independent of `sells`, and that independence is the fix: a store that
   * never answers must not blank the plans, because nothing about what a plan
   * *is* came from the store.
   */
  plans: Plan[] | null;

  /**
   * The top-up packs, from `/v1/packs`. Null while unknown.
   *
   * Ours like the plans, for the same reason and after the same mistake: the
   * minutes a pack grants need no offering to be true, and leaving them
   * store-driven meant a build with no store could describe three plans and no
   * way at all to buy twenty minutes.
   */
  packs: Pack[] | null;

  /**
   * What the store will sell, or null while it has not answered.
   *
   * The empty array and null differ and must stay so: nothing to sell is a shop
   * that is shut, null is one that has not opened its door.
   */
  sells: Sellable[] | null;

  onBuy: (what: Sellable) => void;
  onRestore: () => void;

  /**
   * Where a purchase has got to.
   *
   * `waiting` is the state most products get wrong. A purchase completes on the
   * device, then RevenueCat calls our webhook, then `grant_topup` moves the
   * balance — three moments, and the middle one can be slow.
   */
  state: 'idle' | 'buying' | 'waiting' | 'failed';
}

export function MoreMinutes({
  holding,
  options,
  plans,
  packs,
  sells,
  onBuy,
  onRestore,
  state,
}: MoreMinutesProps) {
  const busy = state === 'buying';
  const offered = plans ?? [];
  const shut = sells !== null && sells.length === 0;
  const lead = leading(plans, options);
  const said = note(state, shut);

  // Null over nothing, the rule the packs already follow: with the plans
  // unread there is nothing to put under "Every month", and a heading over an
  // empty shelf reads as a shelf somebody emptied.
  const Plans = offered.length === 0 ? null : (
    <View style={styles.section}>
      <Text style={styles.heading} accessibilityRole="header">
        Every month
      </Text>
      <View style={styles.cards}>
        {offered.map((plan) => (
          <PlanCard
            key={plan.name}
            plan={plan}
            sold={priceFor(plan, sells)}
            above={above(offered, plan)}
            lead={plan.name === lead}
            busy={busy}
            onBuy={onBuy}
          />
        ))}
      </View>
    </View>
  );

  const Packs = (packs ?? []).length === 0 ? null : (
    <View style={styles.section}>
      <Text style={styles.heading} accessibilityRole="header">
        Just this once
      </Text>

      {/*
        One grouped list rather than three floating cards, because a pack IS a
        different kind of object from a plan and should not be drawn as one: a
        row you pick off a short list, against a card you consider. The plans
        keep the card, and the difference in density is what stops six
        near-identical white rectangles reading as one undifferentiated column.
      */}
      <View style={styles.group}>
        {(packs ?? []).map((pack, at) => {
          // Ours describes it; the store prices it. A pack with no price is
          // still worth naming — it says what could be bought once there is a
          // till.
          const sold = (sells ?? []).find((what) => what.grants === pack.name) ?? null;

          return (
            <Pressable
              key={pack.name}
              testID="sellable"
              accessibilityRole="button"
              accessibilityLabel={
                sold === null ? pack.title : `${pack.title}, ${sold.price}`
              }
              disabled={busy || sold === null}
              onPress={() => sold !== null && onBuy(sold)}
              style={({ pressed }) => [
                styles.pack,
                at > 0 && styles.divided,
                pressed && styles.pressed,
                busy && styles.busy,
              ]}
            >
              {/* Shrinks rather than crushing the price in a long locale. */}
              <View style={styles.packWords}>
                <Text style={styles.packTitle}>{pack.title}</Text>
                <Text style={styles.packDetail}>{`${pack.minutes} minutes`}</Text>
              </View>
              {sold !== null && <Text style={styles.packPrice}>{sold.price}</Text>}
            </Pressable>
          );
        })}
      </View>

      {/*
        §4.5 point 3 — "the minutes are the credit". Beside the packs rather
        than the plans, because it is the answer to "am I wasting this if I
        subscribe later", and that question is asked here.
      */}
      <Text style={styles.kept}>Minutes you buy stay yours and never expire.</Text>
    </View>
  );

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      {/*
        The standing. Title and balance are one unit and are spaced as one —
        they used to sit the same distance apart as two unrelated cards.
      */}
      <Text style={styles.title} accessibilityRole="header">
        More time in the room
      </Text>

      {holding !== null && (
        <Text style={styles.holding}>{`You have ${holding} minutes.`}</Text>
      )}

      {/*
        Anything the screen has to say about buying, in one band directly under
        the balance — never as a loose grey line in the flow.

        Position is the fix as much as the ground is. "Buying is not available
        on this build yet" used to sit BELOW both sections, three hundred points
        beneath the missing prices it was explaining; and "adding them now",
        which is the most important sentence on the screen the moment it
        appears, was set in the smallest type on it.
      */}
      {said !== null && (
        <View style={[styles.band, said.wrong && styles.bandWrong]}>
          <Text
            style={[styles.said, said.wrong && styles.saidWrong]}
            accessibilityLiveRegion={said.live ? 'polite' : 'none'}
          >
            {said.text}
          </Text>
        </View>
      )}

      {/* §4.5's ordering, and the only thing the store decides about layout. */}
      {options?.upgradeFirst ? (
        <>
          {Plans}
          {Packs}
        </>
      ) : (
        <>
          {Packs}
          {Plans}
        </>
      )}

      {/*
        Housekeeping, past a rule and a full gap. Restore is not an offer and
        must not read as one — but it is also an App Store requirement and a
        real case (reinstall, second device), so it is never conditional on
        there being a store to restore from. An empty `sells` is the same
        answer for "no store configured" as for "the store did not respond",
        and hiding this on the second would take it away from a paying customer
        at the exact moment they need it.
      */}
      <View style={styles.housekeeping}>
        <Pressable
          onPress={onRestore}
          accessibilityRole="button"
          style={({ pressed }) => [styles.restore, pressed && styles.pressed]}
        >
          <Text style={styles.restoreText}>Restore a previous purchase</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}

/**
 * The one thing the screen has to say about buying right now, or nothing.
 *
 * At most one is ever true, and the order encodes which fact dominates. A shut
 * shop first: against `unconfiguredStore()` there was no attempt and no till,
 * so "your store will have the details" would send somebody looking for
 * details nobody has — which is what the architect saw after tapping Restore
 * on a build with no offering.
 *
 * `live` is false for the shut shop alone. It is true on arrival rather than
 * newly true, and a live region exists to announce a change.
 */
function note(
  state: MoreMinutesProps['state'],
  shut: boolean,
): { text: string; wrong: boolean; live: boolean } | null {
  if (shut) {
    return {
      text: 'Buying is not available on this build yet.',
      wrong: false,
      live: false,
    };
  }
  if (state === 'waiting') {
    return {
      text: 'Thank you — adding them now. This can take a moment.',
      wrong: false,
      live: true,
    };
  }
  if (state === 'failed') {
    return {
      text: 'That did not go through. Your store will have the details.',
      wrong: true,
      live: true,
    };
  }
  return null;
}

/**
 * Which plan gets the brand ground, or none.
 *
 * The rung above the one they hold — never the top of the ladder by default,
 * and never the plan they are already on. `nextTier` is the server's answer and
 * is null for somebody who has bought every rung, which is a real state: there
 * is nothing to lead with, and highlighting something anyway would be selling
 * an upgrade that does not exist.
 */
function leading(plans: Plan[] | null, options: PurchaseOptions | null): string | null {
  if (plans === null || options?.nextTier == null) return null;
  return plans.some((plan) => plan.name === options.nextTier) ? options.nextTier : null;
}

/**
 * Whether this rung sits above the one they hold.
 *
 * **Only a plan above the current one may be bought**, and the bug this closes
 * is not cosmetic: a Pro subscriber was being offered "Get Starter" — a
 * downgrade wearing an upgrade's button, which takes money for less room.
 *
 * Ladder order is the array order, because `/v1/plans` publishes
 * `UPGRADE_LADDER` cheapest-first and that ordering is the server's to own. A
 * client comparing tier names would need its own copy of the ladder, which is
 * the second table that endpoint exists to prevent.
 *
 * Nobody current — a tier off the ladder, like `pro_annual` — means nothing is
 * above them here, and nothing is offered. Silence beats guessing which of the
 * rungs listed a person on a different plan should be sold.
 */
function above(plans: Plan[], plan: Plan): boolean {
  const held = plans.findIndex((rung) => rung.current);
  return held !== -1 && plans.indexOf(plan) > held;
}

/**
 * What the store charges for this rung, or null.
 *
 * Matched on `grants` rather than on `id`, because the product identifiers
 * belong to the console and neither store lets one be renamed once created —
 * so the join is carried explicitly by whoever configures it.
 */
function priceFor(plan: Plan, sells: Sellable[] | null): Sellable | null {
  return (sells ?? []).find((what) => what.grants === plan.name) ?? null;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
  /**
   * No `gap`. Every interval on this screen is stated by the thing that owns
   * it, because a container gap ADDS to a child's margin — the sections used
   * to sit 28 apart, which is a number nobody chose and was the only spacing
   * contrast on the screen.
   */
  content: { padding: space.screen, paddingBottom: space.major },

  title: { ...type.headlineLg, color: color.onSurface },
  /** Tight to the title: the two are one statement of where you stand. */
  holding: { ...type.bodyLg, color: color.onSurfaceVariant, marginTop: space.hair },

  band: {
    marginTop: space.base,
    padding: space.snug,
    borderRadius: radius.control,
    backgroundColor: color.card,
  },
  /** A failure is bounded rather than coloured in — the words carry it. */
  bandWrong: { borderWidth: StyleSheet.hairlineWidth, borderColor: color.danger },
  said: { ...type.bodyMd, color: color.onSurfaceVariant },
  saidWrong: { color: color.danger },

  /** The interval between the two offers, and from the standing to the first. */
  section: { marginTop: space.section },
  heading: { ...type.labelLg, color: color.onSurfaceVariant, marginBottom: space.snug },
  cards: { gap: space.snug },

  /** The packs as one list, in the app's established grouped-row idiom. */
  group: {
    backgroundColor: color.card,
    borderRadius: radius.card,
    paddingHorizontal: space.base,
  },
  pack: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: space.base,
    paddingVertical: space.base,
    minHeight: 44,
  },
  divided: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: color.hairline },
  packWords: { flexShrink: 1 },
  packTitle: { ...type.labelLg, color: color.onSurface },
  packDetail: { ...type.bodySm, color: color.onSurfaceVariant },
  packPrice: { ...type.bodyLg, color: color.onSurfaceVariant },
  kept: { ...type.bodySm, color: color.onSurfaceVariant, marginTop: space.snug },

  pressed: { opacity: 0.7 },
  busy: { opacity: 0.5 },

  /** Past a rule and a full gap: not an offer, and drawn as not one. */
  housekeeping: {
    marginTop: space.major,
    paddingTop: space.base,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.hairline,
  },
  restore: { paddingVertical: space.snug, minHeight: 44, justifyContent: 'center' },
  restoreText: { ...type.bodySm, color: color.onSurfaceVariant, textAlign: 'center' },
});
