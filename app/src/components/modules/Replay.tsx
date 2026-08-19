import { Pressable, StyleSheet, Text, View } from 'react-native';

import { color, space, type } from '../../theme/tokens';

/**
 * Hear one of the coach's replies again.
 *
 * **This is what makes autoplay safe rather than merely bold.** A reply speaks
 * itself the moment it arrives, which is the only thing that makes the debrief
 * a conversation — nobody taps a button to hear somebody answer them. But the
 * debrief is unmetered, and unmetered means it gets used where the room never
 * would: a train, an open-plan office, a bed at midnight. Sound arriving
 * unbidden there is missed rather than unwelcome, and the words are already on
 * screen. This is the second half of that bargain.
 *
 * Deliberately small and quiet. It sits under a line that has already been
 * spoken, so it is an afterthought by construction; drawn any louder it would
 * compete with "Answer it again", which is the control this screen exists for.
 * Set in the same burnt orange as the panelist name so it reads as belonging to
 * the coach's line rather than as a new kind of thing.
 */

export interface ReplayProps {
  /** Base64 PCM16, straight from the turn that produced it. */
  speech: string;
  onReplay: (speech: string) => void;
}

export function Replay({ speech, onReplay }: ReplayProps) {
  // A turn whose audio never arrived still has its caption, and offering to
  // play nothing would be a control that does nothing when pressed.
  if (speech.length === 0) {
    return null;
  }

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Hear that again"
      onPress={() => onReplay(speech)}
      // 44pt of touch target on a 20pt label, per HIG. `hitSlop` rather than
      // padding, so the target grows without the line moving.
      hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
      style={({ pressed }) => [styles.control, pressed && styles.pressed]}
    >
      <View style={styles.mark} />
      <Text style={styles.label}>Hear that again</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  control: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.tight,
    marginTop: space.tight,
    alignSelf: 'flex-start',
  },
  pressed: { opacity: 0.6 },

  /**
   * A play triangle drawn in borders rather than shipped as an asset.
   *
   * Nine pixels of geometry does not justify an icon dependency or a file in
   * the bundle, and a glyph would be at the mercy of whichever font resolved.
   */
  mark: {
    width: 0,
    height: 0,
    borderTopWidth: 5,
    borderBottomWidth: 5,
    borderLeftWidth: 8,
    borderTopColor: 'transparent',
    borderBottomColor: 'transparent',
    borderLeftColor: color.primary,
  },

  label: { ...type.labelLg, color: color.primary },
});
