import { Pressable, StyleSheet, Text, View } from 'react-native';

import { color, space, type } from '../../theme/tokens';

/**
 * The way back, drawn rather than assumed.
 *
 * **One screen uses this, and only because a native header cannot serve it.**
 * `rooms/[id]` and `debrief/[id]` both had one of these and both gave it up for
 * a real stack header on 2026-08-20 — a drawn chevron is a reinvented control,
 * and theirs scrolled off the top of the screen besides.
 *
 * `PrepSheet` keeps it, and the reason is the sheet's whole purpose: it is
 * photographed and carried into a real meeting, and a nav bar is in every one
 * of those photographs. Below the content the way out is reachable by thumb and
 * out of frame, which no header can be. See `PrepSheetProps.back`.
 *
 * Not left to the edge-swipe gesture either. **A gesture is invisible**, so
 * nobody is told it exists, and it is unreachable for a screen-reader or
 * switch-control user — an accessibility failure rather than a preference.
 * Reported originally as *"the room detail page from the progress list does not
 * have nav"*.
 *
 * **Do not reach for this on a new screen.** If a pushed screen needs a way
 * back, it wants `headerShown` on its own `Stack.Screen`, not a second drawn
 * chevron — that is how two screens come to disagree about where the way out
 * is.
 *
 * **It says where it goes.** "Back" alone is a direction; "Your rooms" is a
 * destination, and a person deciding whether to press it wants the second.
 */

const CHEVRON = 10;

export interface BackToProps {
  /** Where pressing it lands — "Your rooms", "This room". A place, not a verb. */
  where: string;
  onPress: () => void;
}

export function BackTo({ where, onPress }: BackToProps) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Back to ${where.toLowerCase()}`}
      onPress={onPress}
      // 44pt of target on a 20pt label, per HIG. `hitSlop` rather than padding,
      // so the target grows without pushing the title down the screen.
      hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
      style={({ pressed }) => [styles.back, pressed && styles.pressed]}
    >
      {/*
        Drawn, not a glyph. A 10pt square rotated onto its corner with two of
        its sides showing is a chevron, and it takes the type colour without
        depending on a font that may not carry the character — the same reason
        `DeckAttach` draws its page mark and the tab bar draws its own.
      */}
      <View style={styles.chevron} />
      <Text style={styles.label}>{where}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  back: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.tight,
    alignSelf: 'flex-start',
  },
  pressed: { opacity: 0.6 },

  chevron: {
    width: CHEVRON,
    height: CHEVRON,
    borderLeftWidth: 2,
    borderBottomWidth: 2,
    borderColor: color.onSurfaceVariant,
    transform: [{ rotate: '45deg' }],
  },
  label: { ...type.labelLg, color: color.onSurfaceVariant },
});
