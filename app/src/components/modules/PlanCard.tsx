import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { Plan } from '../../lib/api/purchaseApi';
import type { Sellable } from '../../lib/billing/store';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * One rung, as what it gets you.
 *
 * **Everything here except the price comes from us**, and getting that boundary
 * wrong is what made the first version of this screen useless — it rendered
 * entirely from the store, so with no offering configured it had nothing to say
 * at all. `tiers.py` has held every one of these figures the whole time.
 *
 * The price is the store's and is *absent* rather than invented when there is
 * none. A card that says what you get and cannot yet say the price is a real
 * card; §4.4's table is our pricing intent, not what a till will charge.
 */

export interface PlanCardProps {
  plan: Plan;
  /** What the store will charge for it, or null when nothing is on offer. */
  sold: Sellable | null;
  /**
   * Whether this rung is above the one they hold.
   *
   * A card only grows a buy button when it is. Offering "Get Starter" to a Pro
   * subscriber is a downgrade wearing an upgrade's button, and it takes money
   * for less room than they already have.
   */
  above: boolean;
  lead: boolean;
  busy: boolean;
  onBuy: (what: Sellable) => void;
}

export function PlanCard({ plan, sold, above, lead, busy, onBuy }: PlanCardProps) {
  const on = plan.current;

  return (
    <View style={[styles.card, lead && !on && styles.leading]}>
      <View style={styles.head}>
        <Text style={[styles.title, lead && !on && styles.onLead]}>{plan.title}</Text>
        {on ? (
          <Text style={styles.yours}>Your plan</Text>
        ) : (
          sold !== null && (
            <Text style={[styles.price, lead && styles.onLead]}>{sold.price}</Text>
          )
        )}
      </View>

      {/*
        The allowance first, in the largest honest unit — §4.6: "'3 hours of
        executive-level interrogation every month' reads generously. '15
        credits' reads rationed. Identical product."
      */}
      <Text style={[styles.gets, lead && !on && styles.onLead]}>{allowance(plan)}</Text>

      {/*
        Unlimited coaching on EVERY card rather than once at the bottom. §4.6
        asks for it "at the top of every tier card, not in a footnote", and it
        is the metering boundary made visible: §4.1 meters the room and nothing
        after it, so this is the differentiator rather than a perk.
      */}
      <Text style={[styles.gets, lead && !on && styles.onLead]}>
        Unlimited coaching and sparring
      </Text>

      <Text style={[styles.detail, lead && !on && styles.onLead]}>
        {`${plan.seats} panelists · rooms kept ${plan.retentionDays} days · ${plan.maxUploadMb}MB decks`}
        {plan.mayAuthor ? ' · write your own panelist' : ''}
      </Text>

      {/*
        A button only for a rung above this one, priced, and not the one they
        hold. A disabled "Buy" against an unconfigured store is a control that
        exists to be refused; saying nothing is the honest shape.
      */}
      {above && sold !== null && (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Get ${plan.title}, ${sold.price}`}
          disabled={busy}
          onPress={() => onBuy(sold)}
          style={({ pressed }) => [
            styles.buy,
            lead && styles.buyOnLead,
            pressed && styles.pressed,
            busy && styles.busy,
          ]}
        >
          <Text style={[styles.buyLabel, lead && styles.buyLabelOnLead]}>
            {`Get ${plan.title}`}
          </Text>
        </Pressable>
      )}
    </View>
  );
}

/**
 * The allowance, in the unit that reads most generously while staying exact.
 *
 * **The free tier is never described as monthly.** Its fifteen minutes are for
 * life, and "15 minutes a month" would describe a better plan than the one that
 * exists — a promise the ledger would refuse to keep the second time somebody
 * came back for it.
 *
 * Hours only where they are whole. "2.5 hours" is not more generous than "150
 * minutes", it is just harder to check.
 */
export function allowance(plan: Plan): string {
  if (!plan.renews) return `${plan.minutes} minutes to start`;

  const hours = plan.minutes / 60;
  return Number.isInteger(hours) && hours >= 2
    ? `${hours} hours a month`
    : `${plan.minutes} minutes a month`;
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: color.card,
    borderRadius: radius.card,
    padding: space.base,
    gap: space.tight,
  },
  /** The rung §4.5 puts first. Brand ground, used once on the screen. */
  leading: { backgroundColor: color.primary },

  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' },
  title: { ...type.headlineMd, color: color.onSurface },
  price: { ...type.bodyLg, color: color.onSurfaceVariant },
  onLead: { color: color.onPrimary },

  /** Stated rather than sold: a fact about the plan, in the reading size. */
  yours: { ...type.labelLg, color: color.onSurfaceVariant },

  gets: { ...type.bodyLg, color: color.onSurface },
  detail: { ...type.bodySm, color: color.onSurfaceVariant },

  buy: {
    marginTop: space.tight,
    paddingVertical: space.snug,
    borderRadius: radius.pill,
    backgroundColor: color.primary,
    minHeight: 44,
    justifyContent: 'center',
  },
  /** On the brand ground the button inverts, or it disappears into the card. */
  buyOnLead: { backgroundColor: color.onPrimary },
  buyLabel: { ...type.labelLg, color: color.onPrimary, textAlign: 'center' },
  buyLabelOnLead: { color: color.primary },

  pressed: { opacity: 0.7 },
  busy: { opacity: 0.5 },
});
