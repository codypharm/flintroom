import { useEffect, useState } from 'react';
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
  onReplay: () => void;
  /**
   * Whether there is anything to play.
   *
   * The control knows nothing about where the audio comes from, and the two
   * callers differ: a coaching turn holds its own base64 and has none if
   * synthesis failed, while the opening always *can* be played because the
   * server will speak the stored words again on request. So the caller decides
   * and this only draws.
   */
  available?: boolean;
  /**
   * The coach is mid-sentence — #107 item 9.
   *
   * The control stays in place but stops being a control: it says
   * "Speaking…" instead of offering to play a voice over the one already
   * talking. In place rather than removed, because a control that vanishes
   * while audio plays moves the layout under a reading eye, and it comes
   * right back. Pressing it in this state does nothing — two coach voices
   * on one speaker is the failure the state exists to prevent.
   */
  disabled?: boolean;
}

export function Replay({ onReplay, available = true, disabled = false }: ReplayProps) {
  /**
   * Pressed, and the audio has not started yet — #107 follow-up, 2026-08-28.
   *
   * The tap's work is real (voice engine setup on first use, then decode) but
   * it used to be silent: the control sat unchanged for seconds and read as
   * ignored. Held here rather than threaded from the route, because only the
   * pressed control should say it — a dozen siblings share one `disabled`.
   * Cleared when the audio starts (`disabled` arriving is the signal), and by
   * a timeout when it never does, so a failed fetch cannot strand the label.
   */
  const [getting, setGetting] = useState(false);

  useEffect(() => {
    if (disabled) setGetting(false);
  }, [disabled]);

  useEffect(() => {
    if (!getting) return;
    const abandon = setTimeout(() => setGetting(false), 8000);
    return () => clearTimeout(abandon);
  }, [getting]);

  // A turn whose audio never arrived still has its caption, and offering to
  // play nothing would be a control that does nothing when pressed.
  if (!available) {
    return null;
  }

  const resting = !disabled && !getting;
  const label = disabled ? 'Speaking…' : getting ? 'Getting it…' : 'Hear that again';

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={resting ? 'Hear that again' : 'The coach is speaking'}
      accessibilityState={{ disabled: !resting }}
      disabled={!resting}
      onPress={() => {
        setGetting(true);
        onReplay();
      }}
      // 44pt of touch target on a 20pt label, per HIG. `hitSlop` rather than
      // padding, so the target grows without the line moving.
      hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
      style={({ pressed }) => [styles.control, (pressed || !resting) && styles.pressed]}
    >
      {/* No play triangle unless it is an offer — a play glyph beside
          "Speaking…" or "Getting it…" would be an instruction beside a status. */}
      {resting && <View style={styles.mark} />}
      <Text style={styles.label}>{label}</Text>
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
