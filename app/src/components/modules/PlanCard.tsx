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
 *
 * **The card is read top-down in one order and is spaced to say so.** Its four
 * registers used to be 24 / 18 / 18 / 14, which is three sizes for four jobs —
 * the allowance, which is the whole point of the rung, sat at the same weight
 * as the line beneath it. They are now title, allowance, promise, facts, and
 * the facts sit under a rule because they are specification rather than sell.
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
  /**
   * The same rung on a yearly bill, or null — #107 item 8.
   *
   * A quieter second way to buy the card it sits on, never a rung of its own:
   * `tiers.py` keeps `pro_annual` off the ladder because it is the same
   * capability on another billing period, and a card for it would offer
   * somebody a sideways move dressed as a step up.
   */
  annual: Sellable | null;
  busy: boolean;
  onBuy: (what: Sellable) => void;
}

export function PlanCard({ plan, sold, above, lead, annual, busy, onBuy }: PlanCardProps) {
  const on = plan.current;
  /** The lead's own ground, and only where it is not also the plan they hold. */
  const front = lead && !on;

  return (
    <View testID={`plan-${plan.name}`} style={[styles.card, front && styles.leading]}>
      {/*
        Why this card is on the brand ground, said out loud — #107 item 7. The
        highlight alone read as "this is my plan" to the person holding Free,
        which is the one thing it must never say.
      */}
      {front && <Text style={styles.suggested}>Suggested</Text>}
      <View style={styles.head}>
        <Text style={[styles.title, front && styles.onLead]} numberOfLines={1}>
          {plan.title}
        </Text>
        {on ? (
          <Text style={styles.yours}>Your plan</Text>
        ) : (
          sold !== null && (
            // `front` like every sibling — `lead` alone was identical only
            // because the lead can never be the plan already held.
            <Text style={[styles.price, front && styles.onLead]}>{sold.price}</Text>
          )
        )}
      </View>

      {/*
        The allowance first, in the largest honest unit — §4.6: "'3 hours of
        executive-level interrogation every month' reads generously. '15
        credits' reads rationed. Identical product."

        Given its own register rather than sharing one with the line below it.
        It is the answer to the only question this card exists to answer.
      */}
      <Text style={[styles.gets, front && styles.onLead]}>{allowance(plan)}</Text>

      {/*
        Unlimited coaching on EVERY card rather than once at the bottom. §4.6
        asks for it "at the top of every tier card, not in a footnote", and it
        is the metering boundary made visible: §4.1 meters the room and nothing
        after it, so this is the differentiator rather than a perk.

        Full contrast and directly under the allowance — one register down, not
        one rank down. Demoting it to the grey of the facts row would put it in
        exactly the footnote §4.6 forbids.
      */}
      <Text style={[styles.promise, front && styles.onLead]}>
        Unlimited coaching and sparring
      </Text>

      {/*
        The specification, under a rule because it is a different kind of
        sentence — checked rather than read. Each fact is its own Text so the
        row wraps BETWEEN facts; the single joined string it replaces broke
        mid-fact on a narrow screen and read as one long sentence about
        nothing.
      */}
      <View style={[styles.facts, front && styles.factsOnLead]}>
        {specifics(plan).map((fact) => (
          <Text key={fact} style={[styles.fact, front && styles.onLead]}>
            {fact}
          </Text>
        ))}
      </View>

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
            front && styles.buyOnLead,
            pressed && styles.pressed,
            busy && styles.busy,
          ]}
        >
          <Text style={[styles.buyLabel, front && styles.buyLabelOnLead]}>
            {`Get ${plan.title}`}
          </Text>
        </Pressable>
      )}

      {/*
        The year, under the month and quieter than it. Same gate as the buy
        button — a rung above, priced by the store — because it is the same
        purchase on a different cadence, not a different thing to sell.
      */}
      {above && annual !== null && (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Get a year of ${plan.title}, ${annual.price}`}
          disabled={busy}
          onPress={() => onBuy(annual)}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
          style={({ pressed }) => [styles.year, pressed && styles.pressed, busy && styles.busy]}
        >
          <Text style={[styles.yearLabel, front && styles.onLead]}>
            {`or ${annual.price} a year`}
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

/**
 * What else the rung carries, as separate facts rather than one sentence.
 *
 * Same words as the joined string this replaces — the middots are gone because
 * the gap between them does that job, and a separator that only exists to be
 * wrapped past is a character somebody has to read.
 */
function specifics(plan: Plan): string[] {
  const facts = [
    `${plan.seats} panelists`,
    `rooms kept ${plan.retentionDays} days`,
    `${plan.maxUploadMb}MB decks`,
  ];
  return plan.mayAuthor ? [...facts, 'write your own panelist'] : facts;
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: color.card,
    borderRadius: radius.card,
    padding: space.base,
  },
  /**
   * The rung §4.5 puts first. Brand ground, used once on the screen.
   *
   * **It also takes more room**, which is the half that was missing: on a
   * scrolling screen a card that leads only by colour has the same footprint
   * as every card it is meant to lead, and the eye reads footprint first.
   * `radius.container` is §9's brand radius and this is the one card on the
   * screen entitled to it.
   */
  leading: { backgroundColor: color.primary, padding: space.loose, borderRadius: radius.container },

  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', gap: space.snug },
  /** Shrinks rather than pushing the price off the card in a long locale. */
  title: { ...type.headlineMd, color: color.onSurface, flexShrink: 1 },
  price: { ...type.bodyLg, color: color.onSurfaceVariant },
  onLead: { color: color.onPrimary },

  /** Stated rather than sold: a fact about the plan, in the reading size. */
  yours: { ...type.labelLg, color: color.onSurfaceVariant },

  /** Small and above the name: a reading instruction, not a feature. */
  suggested: { ...type.labelLg, color: color.onPrimary, marginBottom: space.hair },

  year: { marginTop: space.snug, alignSelf: 'center', minHeight: 32, justifyContent: 'center' },
  yearLabel: { ...type.labelLg, color: color.onSurfaceVariant, textAlign: 'center' },

  /** The point of the rung, one register under its name. */
  gets: { ...type.headlineSm, color: color.onSurface, marginTop: space.snug },
  /** Tight to the allowance, because the two together are "what you get". */
  promise: { ...type.bodyMd, color: color.onSurface, marginTop: space.hair },

  facts: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    columnGap: space.snug,
    rowGap: space.hair,
    marginTop: space.snug,
    paddingTop: space.snug,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.hairline,
  },
  /** The warm hairline vanishes on burnt orange; the rule inverts with it. */
  factsOnLead: { borderTopColor: color.onPrimary },
  fact: { ...type.bodySm, color: color.onSurfaceVariant },

  buy: {
    marginTop: space.base,
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
