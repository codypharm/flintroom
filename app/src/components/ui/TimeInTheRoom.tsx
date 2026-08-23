import { Pressable, StyleSheet, Text, View } from 'react-native';

import { color, radius, space, type } from '../../theme/tokens';

/**
 * How much time this account has in the room.
 *
 * **The wording is the product rule, not a preference.** §4.6 forbids a
 * depleting counter and asks for minutes "framed generously", so this never
 * says "available", "remaining", "left", or "of your allowance". Those four are
 * the counter arriving one adjective at a time: each frames the number as a
 * quantity being consumed rather than one being held.
 *
 * **"You have" is what the rule leaves open, and it is what this was missing.**
 * The chip read *"55 minutes in the room"* and was reported from a phone as
 * uninformative — correctly. Standing alone in a bar on every screen, it can be
 * read three ways: how long a room lasts, how long you have been in one, or
 * what you hold. Only the third is true. A possessive says it outright, and says
 * the opposite of depletion while doing it.
 *
 * **"in the room" does not fit here, and the reason is measured rather than
 * assumed.** The bar leaves about 162pt for this text beside the wordmark. The
 * full sentence needs 258 and the old text needed 183 — so the phrase this
 * replaces was already overflowing on a 393pt phone. "You have 55 minutes" is
 * 158. The product's noun keeps its home on `TablePlan` and the sign-in sheet,
 * which have a sentence to spend on it; here the clock and the surrounding app
 * carry what the minutes are for.
 *
 * **A chip rather than a sentence**, because it is a standing fact about the
 * account rather than something being said. It needs to be readable at a
 * glance and to stop reading like prose the moment the eye moves on.
 *
 * It used to sit above the control that spends it, on Home. It lives in the
 * shared `TopBar` now — the slot the design guide's `TopAppBar` fills with a
 * token pill — so it is on every top-level screen rather than only the one
 * where minutes are spent.
 *
 * The mark is drawn from Views, following every other mark in this app: there
 * is no icon library here, `expo-symbols` is iOS-only, and a Unicode glyph
 * standing in for an icon is a costume. A clock rather than a stopwatch or an
 * hourglass, deliberately — both of those are *countdowns*, and a countdown is
 * the depleting counter drawn instead of written.
 */

export interface TimeInTheRoomProps {
  minutes: number;
  /** Whether there is any at all. The server decides it; this only draws it. */
  any: boolean;
  /**
   * Where a tap on the fact goes — the screen that sells more of it.
   *
   * Optional, and the chip stays a plain statement without it: a bar rendered
   * with no destination must not grow a control that goes nowhere. With it,
   * the fact you tap is the fact the screen answers — the chip is the one
   * place the balance is always visible, and it was the only reading of the
   * balance that led nowhere.
   */
  onPress?: () => void;
}

export function TimeInTheRoom({ minutes, any, onPress }: TimeInTheRoomProps) {
  // Word for word what is drawn. These used to disagree — the label said
  // "until your next top-up" while the screen said "right now" — which is
  // the same defect as a button whose visible and spoken names differ.
  // Singular for exactly one — "You have 1 minutes" was seen on a phone, on
  // the account most likely to be reading this chip closely.
  const unit = minutes === 1 ? 'minute' : 'minutes';
  const label = any ? `You have ${minutes} ${unit}` : 'No minutes right now';

  const said = (
    <>
      <Clock />
      <Text style={styles.said}>
        {any ? (
          <>
            {/* The figure carries the weight and the words around it stay
                quiet, so the number is what the eye finds at a glance. */}
            <Text style={styles.unit}>You have </Text>
            <Text style={styles.figure}>{minutes}</Text>
            <Text style={styles.unit}> {unit}</Text>
          </>
        ) : (
          <Text style={styles.unit}>No minutes right now</Text>
        )}
      </Text>
    </>
  );

  if (onPress === undefined) {
    return (
      <View style={styles.chip} accessibilityRole="text" accessibilityLabel={label}>
        {said}
      </View>
    );
  }

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      // The action, separate from the fact: the label keeps stating what is
      // held, and the hint says where the tap goes.
      accessibilityHint="Opens more time in the room"
      onPress={onPress}
      // The chip stands 36pt in a 52pt bar; the slop is what carries the
      // target to the 44pt floor without growing the pill.
      hitSlop={{ top: 8, bottom: 8, left: 4, right: 4 }}
      style={({ pressed }) => [styles.chip, pressed && styles.pressed]}
    >
      {said}
    </Pressable>
  );
}

/** A face and two hands, at rest. Nothing here is counting down. */
function Clock() {
  return (
    <View style={styles.face}>
      <View style={styles.hourHand} />
      <View style={styles.minuteHand} />
    </View>
  );
}

const FACE = 16;

const styles = StyleSheet.create({
  /**
   * **No `alignSelf`, and its absence is the fix for a reported defect.**
   *
   * This carried `alignSelf: 'flex-start'`, written when the chip lived in a
   * column above the control that spends the minutes — where the cross axis is
   * horizontal and it meant "do not stretch across the screen". Moved into
   * `TopBar`'s row the cross axis becomes vertical, so the identical
   * declaration meant "pin to the top", and it beat the bar's own
   * `alignItems: 'center'` because a child's `alignSelf` always does. Reported
   * as *"the remaining time is close to the top"*.
   *
   * So the chip no longer has an opinion about where it sits. A container that
   * wants it hugging one edge of a column says `alignSelf` at the call site,
   * where the axis it is talking about is visible.
   */
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.tight,
    paddingVertical: space.tight,
    paddingHorizontal: space.snug,
    borderRadius: radius.pill,
    // `surface`, because the bar it sits in became `card`. Two whites would
    // have made the chip a floating clock and a number with no pill around
    // them — the fill is what says "a standing fact" rather than a sentence.
    backgroundColor: color.surface,
  },

  face: {
    width: FACE,
    height: FACE,
    borderRadius: FACE / 2,
    borderWidth: 1.5,
    borderColor: color.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  /**
   * Both hands pinned at the centre and rotated about their own base, so they
   * read as hands rather than as two lines crossing. Ten past ten, which is
   * where a clock is drawn when it is being shown rather than read.
   */
  hourHand: {
    position: 'absolute',
    width: 1.5,
    height: 4,
    backgroundColor: color.primary,
    borderRadius: 1,
    transform: [{ translateY: -2 }],
  },
  minuteHand: {
    position: 'absolute',
    width: 1.5,
    height: 5.5,
    backgroundColor: color.primary,
    borderRadius: 1,
    transform: [{ rotate: '90deg' }, { translateY: -2.75 }],
  },

  pressed: { opacity: 0.6 },

  said: { ...type.bodyMd },
  /** The figure carries the weight; the unit stays quiet beside it. */
  figure: { ...type.labelLg, color: color.onSurface },
  unit: { ...type.bodyMd, color: color.onSurfaceVariant },
});
