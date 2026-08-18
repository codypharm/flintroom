import { Pressable, StyleSheet, Text, View } from 'react-native';

import { color, radius, space, type } from '../../theme/tokens';

/**
 * The account, asked for once there is something to lose.
 *
 * Placed after the plan rather than at launch, which is `docs/onboarding.md`'s
 * decision and its reasoning: the account becomes the way to keep the room they
 * just described, *"rather than a toll gate in front of a stranger"*. Somebody
 * who has filled in a seating chart is not a stranger.
 *
 * **Both buttons are equal weight.** Apple has a rule against making its own
 * option less prominent, and beyond the rule there is no reason to steer:
 * whichever a person already uses is the one that will work first time. So
 * neither is styled as primary, and the order is Apple-then-Google on iOS
 * simply because that is the order iOS users expect.
 *
 * Apple is absent rather than disabled on Android, and that is the module's
 * doing rather than ours — `expo-apple-authentication` has no Android
 * implementation. `appleAvailable` comes from `isAvailableAsync`, which also
 * answers false on an iOS version or a simulator that cannot do it, so a button
 * that would throw when tapped never renders.
 */
export interface SignInSheetProps {
  /** Whether this device can offer Sign in with Apple at all. */
  appleAvailable: boolean;
  busy: boolean;
  /** Said plainly, and never as "something went wrong". */
  refusal: string | null;
  onApple: () => void;
  onGoogle: () => void;
}

export function SignInSheet({
  appleAvailable,
  busy,
  refusal,
  onApple,
  onGoogle,
}: SignInSheetProps) {
  return (
    <View style={styles.sheet}>
      <Text style={styles.title} accessibilityRole="header">
        Keep this room
      </Text>
      <Text style={styles.body}>
        {/* Names what signing in *does*, not what it is. The room they just
            built is the thing at stake, and the minutes are the offer — §4.6
            wants the largest honest unit, stated generously. */}
        Your panel is ready. Sign in to keep it, and take your first 15 minutes
        in the room.
      </Text>

      {appleAvailable && (
        <Way label="Continue with Apple" busy={busy} onPress={onApple} />
      )}
      <Way label="Continue with Google" busy={busy} onPress={onGoogle} />

      {refusal !== null && (
        <Text style={styles.refusal} accessibilityRole="alert">
          {refusal}
        </Text>
      )}
    </View>
  );
}

function Way({
  label,
  busy,
  onPress,
}: {
  label: string;
  busy: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: busy }}
      disabled={busy}
      onPress={onPress}
      style={({ pressed }) => [styles.way, pressed && styles.pressed, busy && styles.dim]}
    >
      <Text style={styles.wayLabel}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  sheet: { padding: space.screen, gap: space.snug },

  title: { ...type.headlineMd, color: color.onSurface },
  body: { ...type.bodyLg, color: color.onSurfaceVariant, marginBottom: space.base },

  way: {
    minHeight: 44,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: space.snug,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: color.onSurface,
  },
  wayLabel: { ...type.labelLg, color: color.onSurface },
  pressed: { opacity: 0.6 },
  dim: { opacity: 0.4 },

  refusal: { ...type.bodyMd, color: color.danger, marginTop: space.tight },
});
