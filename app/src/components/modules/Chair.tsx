import { Pressable, StyleSheet, Text, View } from 'react-native';

import { color, space, type } from '../../theme/tokens';

/**
 * One chair on the table, and the only control this screen really has.
 *
 * A row rather than a shape on a canvas, and that is the accessibility decision
 * rather than a compromise. A drawn table with draggable figures is unreachable
 * by a screen reader, unusable at the largest Dynamic Type sizes, and worse with
 * a thumb on a 390pt phone than a tap is. So the plan is drawn *along* an
 * accessible list: a spine down the left edge stands for the table, and every
 * chair on it is a real button with a spoken label.
 *
 * `position` is shown when the chair is taken, and that number is earned rather
 * than decorative — the server seats archetypes in the order they arrive, so
 * chair one really does speak first. A plan that hid its own order would be
 * asking somebody to make a decision it then refused to show them.
 */
export interface ChairProps {
  label: string;
  /** Which chair this is, 1-based, or null when nobody is in it. */
  position: number | null;
  /** True when the table is full and this chair is empty. */
  unavailable: boolean;
  onPress: () => void;
}

export function Chair({ label, position, unavailable, onPress }: ChairProps) {
  const taken = position !== null;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: taken, disabled: unavailable }}
      accessibilityLabel={
        taken
          ? `${label}, in chair ${position}. Tap to take them out.`
          : unavailable
            ? `${label}. The table is full.`
            : `${label}. Tap to seat them.`
      }
      disabled={unavailable}
      onPress={onPress}
      style={({ pressed }) => [styles.chair, pressed && styles.pressed]}
    >
      <View style={styles.spine}>
        {/* The table edge, continuous behind every chair. Drawn per row rather
            than as one absolute rule so it grows with the text: at the largest
            accessibility sizes the rows get taller and the table gets longer,
            instead of the line ending halfway down a list it no longer fits. */}
        <View style={styles.rail} />
        <View style={[styles.marker, taken && styles.markerTaken]} />
      </View>

      <Text
        style={[
          styles.label,
          taken && styles.labelTaken,
          unavailable && styles.labelUnavailable,
        ]}
      >
        {label}
      </Text>

      {taken && <Text style={styles.position}>{position}</Text>}
    </Pressable>
  );
}

const MARKER = 14;

const styles = StyleSheet.create({
  chair: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.base,
    minHeight: 44,
    paddingVertical: space.snug,
  },
  pressed: { opacity: 0.6 },

  // `justifyContent` centres the bead on the string. Without it the marker sat
  // at the top of its row while the label sat in the middle of the same row, so
  // the rail read as a stem hanging off a pin rather than as a continuous edge
  // — and the drift got worse the taller the row grew, which is exactly what
  // the largest Dynamic Type sizes do to it.
  spine: {
    width: MARKER,
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'stretch',
  },
  rail: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    width: 2,
    backgroundColor: color.hairline,
  },
  marker: {
    width: MARKER,
    height: MARKER,
    borderRadius: MARKER / 2,
    borderWidth: 2,
    borderColor: color.hairline,
    backgroundColor: color.surface,
  },
  markerTaken: { backgroundColor: color.primary, borderColor: color.primary },

  label: { ...type.bodyLg, color: color.onSurfaceVariant, flex: 1 },
  labelTaken: { color: color.onSurface },
  // Dimmed rather than hidden. A chair that vanished when the table filled
  // would read as the app losing options, and somebody who wants a fourth
  // person needs to see that the seat exists before it can mean anything.
  labelUnavailable: { opacity: 0.4 },

  position: { ...type.labelLg, color: color.primary },
});
