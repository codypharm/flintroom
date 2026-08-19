import { Pressable, StyleSheet, Text, View } from 'react-native';

import { color, space, type } from '../../theme/tokens';

/**
 * The way back, drawn rather than assumed.
 *
 * `_layout.tsx` hides every stack header, for a good reason — each screen draws
 * its own title, and a header would stack a second one above it — and it argued
 * that back was still available because the stack keeps the edge-swipe gesture.
 * That is true and it was not enough. **A gesture is invisible**, so nobody is
 * told it exists, and it is unreachable for a screen-reader or switch-control
 * user, which makes it an accessibility failure rather than a preference.
 *
 * It surfaced on the room a Progress bar opens: a screen you dip into from a
 * list and come back from, where a linear flow's "you finish and move on" does
 * not apply. Reported as *"the room detail page from the progress list does not
 * have nav"*.
 *
 * Lifted from `SignInSheet`, which had grown one of these privately. A second
 * hand-rolled back control is how two screens come to disagree about where the
 * way out is, and this is the one control on any screen that must never be a
 * surprise.
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
