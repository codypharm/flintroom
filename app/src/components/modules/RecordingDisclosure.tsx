import { Pressable, StyleSheet, Text, View } from 'react-native';

import { color, radius, space, type } from '../../theme/tokens';

/**
 * What Flintroom keeps, said once, before the first room.
 *
 * `docs/session-retention.md` chose recording on by default with a disclosure
 * rather than opt-in, and put the whole weight of that on this sheet. It sits
 * ahead of the system microphone prompt on purpose: `docs/onboarding.md` fixes
 * the ask at the moment its reason is self-evident, and this is the reason.
 *
 * Two truths, in the order they matter to the person reading. The microphone is
 * why the app works at all and is expected. That the room is *kept* afterwards
 * is the thing they would not assume, so it gets the weight.
 */

export interface RecordingDisclosureProps {
  /** The account's own window, from `GET /v1/preferences/recording`. */
  retentionDays: number;
  onContinue: () => void;
}

export function RecordingDisclosure({
  retentionDays,
  onContinue,
}: RecordingDisclosureProps) {
  return (
    <View style={styles.sheet}>
      <Text style={styles.heading} accessibilityRole="header">
        Rooms are recorded
      </Text>

      {/*
        Four facts, one sentence each, and nothing else. Every line that is
        merely true rather than necessary costs attention on the one screen
        where being read is the entire point — and a disclosure people skip is
        not a disclosure.

        What was cut and why: that the panel interrupts (interesting, not
        needed); that transcripts outlive the audio (a second retention rule the
        policy carries, and it dilutes the one that matters here).
      */}
      <Text style={styles.body}>
        Your microphone is on while you are in the room.
      </Text>

      <Text style={styles.body}>
        Each room is saved, your voice and the panel&rsquo;s, so you can play it
        back. Recordings are deleted after {retentionDays} days.
      </Text>

      <Text style={styles.aside}>
        Delete a room or turn off saving in Settings.
      </Text>

      <Pressable
        accessibilityRole="button"
        onPress={onContinue}
        style={({ pressed }) => [styles.action, pressed && styles.actionPressed]}
      >
        <Text style={styles.actionLabel}>Enter the room</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  sheet: {
    backgroundColor: color.card,
    borderTopLeftRadius: radius.container,
    borderTopRightRadius: radius.container,
    paddingHorizontal: space.screen,
    paddingTop: space.section,
    paddingBottom: space.loose,
    gap: space.base,
  },

  heading: {
    ...type.headlineMd,
    color: color.onSurface,
    // More space below a heading than the body's own rhythm gives it, and none
    // above — the sheet edge already supplies that.
    marginBottom: space.tight,
  },

  body: {
    ...type.bodyMd,
    color: color.onSurfaceVariant,
  },

  aside: {
    ...type.bodySm,
    color: color.onSurfaceVariant,
    marginTop: space.tight,
  },

  action: {
    marginTop: space.loose,
    minHeight: 52,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: color.primary,
    borderRadius: radius.pill,
    paddingHorizontal: space.loose,
  },

  // Pressed state rather than none. A control with no feedback on a sheet that
  // gates entry to the room reads as an app that did not register the tap.
  actionPressed: { opacity: 0.85 },

  actionLabel: {
    ...type.labelLg,
    fontSize: 16,
    color: color.onPrimary,
  },
});
