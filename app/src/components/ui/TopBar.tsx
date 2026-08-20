import { Image, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { type Held } from '../../lib/api/balanceApi';
import { MARK, boxFor, padFor } from '../../lib/brand/mark';
import { color, space, type } from '../../theme/tokens';
import { TimeInTheRoom } from './TimeInTheRoom';

/**
 * The bar every top-level screen wears — the app's own header.
 *
 * **This is the thing the mockups call `TopAppBar (Shared Component)`**
 * (`design-guide/profile/code.html:206`) and it appears in nine of the eleven
 * screen mockups. It was never built. The app instead had every screen begin
 * with a title inside its own ScrollView, which scrolls away and leaves the top
 * of the phone empty — so Flintroom appeared nowhere once you moved, and the
 * shape somebody recognises from WhatsApp or LinkedIn was simply absent.
 *
 * **Mark and wordmark left, time in the room right.** That is the mockups'
 * layout, kept. Their *content* is retired and deliberately not carried over:
 * the wordmark said "PitchGo AI", and the right-hand pill said "120 Tokens" —
 * a name this product no longer has and a counter `CLAUDE.md` forbids twice
 * over, once as the retired token economy and once as the rule against ever
 * showing a depleting count. The slot survives; what fills it is minutes, said
 * the way §4.6 asks them to be said.
 *
 * **No hamburger.** Home and the interrogation mockups put a `menu` button at
 * the leading edge, and there is no drawer in this app to open — the tab bar is
 * the navigation. A control that opens nothing is worse than a statement, which
 * is the call `PanelSetup` and the date row both already made.
 *
 * **Not on every screen, and the exceptions are each argued.** The live
 * interrogation does not wear it, despite the mockup: the room is the one
 * surface on `roomGround`, with the phone flat on a desk, and a bright brand
 * bar there is `tokens.ts`'s "lamp pointed at the ceiling" — with a balance
 * beside it during a *metered* session, which is the closest thing to the
 * paywall the metering rules forbid mid-room. The pushed screens wear a stack
 * header with a back button instead, because one bar is enough and the way back
 * matters more than the brand. Sign-in draws the same lockup larger, on
 * purpose. The prep sheet wears nothing, because it is photographed.
 *
 * Draws its own top inset rather than sitting inside a `SafeAreaView`: it is
 * handed to the navigator as a `header`, so it is the topmost thing on the
 * screen and owns the space the status bar occupies.
 */

/** The mark at the wordmark's own scale, as in the sign-in lockup. */
const MARK_HEIGHT = 22;

export interface TopBarProps {
  /** The account's time, or null until it arrives. Never a spinner. */
  held: Held | null;
}

export function TopBar({ held }: TopBarProps) {
  const inset = useSafeAreaInsets();

  return (
    <View style={[styles.bar, { paddingTop: inset.top }]}>
      <View style={styles.row}>
        <View style={styles.lockup}>
          <Image
            testID="mark"
            source={MARK}
            style={styles.mark}
            resizeMode="contain"
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            accessibilityIgnoresInvertColors
          />
          <Text style={styles.brand} accessibilityRole="header">
            Flintroom
          </Text>
        </View>

        {/* Absent rather than a placeholder until the balance lands. A skeleton
            chip would be the app pretending to know something it does not, and
            the row's height is fixed so nothing below it moves when the real
            one arrives. */}
        {held !== null && <TimeInTheRoom minutes={held.minutes} any={held.any} />}
      </View>
    </View>
  );
}

const BAR = 52;

const styles = StyleSheet.create({
  bar: { backgroundColor: color.surface },
  /**
   * Fixed height, so the chip arriving late does not shift the screen.
   *
   * No bottom hairline. The mockups draw this bar flat on the same ground as
   * the content — `flat no shadows` in their own class list — and a rule under
   * it would separate the brand from the screen it belongs to.
   */
  row: {
    height: BAR,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: space.screen,
  },
  lockup: { flexDirection: 'row', alignItems: 'center', gap: space.tight },
  /**
   * Pulled back to the ink on both sides.
   *
   * `splash-icon.png` frames the mark with transparency — at this box, 11pt of
   * nothing either side of 19pt of logo. Without the negative margin the 8pt
   * gap to the wordmark reads as 19 and the whole lockup starts 11pt inside the
   * screen margin everything else is aligned to. See `padFor`.
   */
  mark: {
    width: boxFor(MARK_HEIGHT),
    height: boxFor(MARK_HEIGHT),
    marginHorizontal: -padFor(boxFor(MARK_HEIGHT)),
  },
  /**
   * `primary`, per the mockups, which set the wordmark in the brand colour on
   * every screen that carries this bar. It is the one place burnt orange is
   * allowed to be constant rather than sparing — a logotype is not an action.
   */
  brand: { ...type.headlineSm, color: color.primary },
});
