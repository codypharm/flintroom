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
 *
 * ---
 *
 * **Anchored rather than centred.** This sheet holds a heading, two lines, and
 * — on Android, where Apple cannot render — a single button. Centring that
 * vertically put the one thing to tap in the middle of the screen with three
 * hundred points of nothing on either side of it, which reads as a screen that
 * failed to load rather than as a deliberately quiet one. Framing at the top,
 * the ways in at the bottom under the thumb: the emptiness becomes the space
 * between two placed things instead of the absence of a third.
 *
 * The heading matches `TablePlan`'s opening question in size, because the plan
 * and this are two states of one screen rather than two screens.
 *
 * **Nothing fills the middle, and that is now a decision rather than a gap.**
 * Three things were tried there and all three were removed by the architect:
 * the seated chairs read back (taken for the panel on sight, which is what
 * `plan.ts` keeps on the server), the app icon (about the company, on the one
 * screen that is about the product), and a drawing of the table. The space is
 * the answer. This screen is crossed once, in a few seconds, on the way to a
 * provider sheet — it does not need to hold anybody's attention, and every
 * attempt to make it try was a thing competing with the only two controls that
 * matter.
 */
export interface SignInSheetProps {
  /** Whether this device can offer Sign in with Apple at all. */
  appleAvailable: boolean;
  busy: boolean;
  /** Said plainly, and never as "something went wrong". */
  refusal: string | null;
  onApple: () => void;
  onGoogle: () => void;
  /**
   * Back to the plan, with every answer still in it — or null.
   *
   * Null on the launch gate, which is where this sheet now appears first: there
   * is genuinely nothing behind it, and a control offering to return to nowhere
   * is worse than no control.
   *
   * Non-null on the path it was built for. The plan used to be held in the
   * route's state and posted with sign-up, so until this existed a back gesture
   * left onboarding altogether and took five answers with it that had never
   * reached the server.
   */
  onBack: (() => void) | null;
}

export function SignInSheet({
  appleAvailable,
  busy,
  refusal,
  onApple,
  onGoogle,
  onBack,
}: SignInSheetProps) {
  return (
    <View style={styles.sheet}>
      <View style={styles.said}>
        {onBack !== null && (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Back to your plan"
          accessibilityState={{ disabled: busy }}
          disabled={busy}
          onPress={onBack}
          hitSlop={space.snug}
          style={({ pressed }) => [styles.back, pressed && styles.pressed]}
        >
          {/* Drawn, not a glyph: a 10pt square rotated onto its corner with two
              of its sides showing is a chevron, and it inherits the type colour
              without a font that may not carry the character. */}
          <View style={styles.chevron} />
          <Text style={styles.backLabel}>Your plan</Text>
        </Pressable>
        )}

        <Text style={styles.title} accessibilityRole="header">
          Keep this room
        </Text>
        <Text style={styles.body}>
          {/* Names what signing in *does*, and claims nothing the screen is not
              showing. It opened "Your panel is ready" for a while, which was an
              assertion about an unseen thing in a word nothing around it used —
              the heading says room, and Panel is what the server casts from
              these answers.

              §4.6 wants the minutes stated as the largest honest unit and given
              generously, which is why they are here and first-person. */}
          Sign in to keep this plan. Your first 15 minutes in the room are on us.
        </Text>
      </View>

      <View style={styles.ways}>
        {/* A tap used to produce one visible effect: the button faded to 40%.
            Between the provider's sheet closing and the route replacing, this
            screen sits on a round trip to our server and said nothing about it.

            Polite rather than an alert, and deliberately: `alert` interrupts
            whatever a screen reader is saying, which is right for a refusal
            and wrong for a wait. The two never appear together — starting a
            sign-in clears the last refusal. */}
        {busy && (
          <Text style={styles.waiting} accessibilityLiveRegion="polite">
            Signing you in…
          </Text>
        )}

        {refusal !== null && (
          <Text style={styles.refusal} accessibilityRole="alert">
            {refusal}
          </Text>
        )}

        {appleAvailable && (
          <Way label="Continue with Apple" busy={busy} onPress={onApple} />
        )}
        <Way label="Continue with Google" busy={busy} onPress={onGoogle} />
      </View>
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

const CHEVRON = 10;

const styles = StyleSheet.create({
  sheet: {
    flex: 1,
    paddingHorizontal: space.screen,
    paddingTop: space.base,
    paddingBottom: space.loose,
    justifyContent: 'space-between',
  },

  // The two ends of the sheet. Inside each, siblings sit close; between them is
  // whatever the screen has left, which is the point of anchoring rather than
  // centring.
  said: { gap: space.base },
  ways: { gap: space.snug },

  back: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: space.tight,
    minHeight: 44,
    // Pulled up against the safe area so the back control sits where a native
    // one would, rather than adding a fifth vertical interval to the stack.
    marginBottom: -space.tight,
  },
  chevron: {
    width: CHEVRON,
    height: CHEVRON,
    borderLeftWidth: 2,
    borderBottomWidth: 2,
    borderColor: color.onSurfaceVariant,
    transform: [{ rotate: '45deg' }],
  },
  backLabel: { ...type.labelLg, color: color.onSurfaceVariant },

  title: { ...type.headlineLg, color: color.onSurface },
  body: { ...type.bodyLg, color: color.onSurfaceVariant },

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

  // Above the buttons rather than below them: a refusal that appears under the
  // control pushes nothing and is read after the second tap. Above, it lands
  // between the reason and the retry.
  refusal: { ...type.bodyMd, color: color.danger },
  // Not `danger`. Waiting is not a failure, and colouring it as one is how an
  // interface teaches people to distrust its own red.
  waiting: { ...type.bodyMd, color: color.onSurfaceVariant },
});
