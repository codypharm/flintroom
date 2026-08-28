import {
  AppleAuthenticationButton,
  AppleAuthenticationButtonStyle,
  AppleAuthenticationButtonType,
} from 'expo-apple-authentication';
import { Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { MARK as MARK_SOURCE, padFor } from '../../lib/brand/mark';

import { color, radius, space, type } from '../../theme/tokens';

/**
 * The account, asked for once there is something to lose.
 *
 * Placed after the plan rather than at launch, which is `docs/onboarding.md`'s
 * decision and its reasoning: the account becomes the way to keep the room they
 * just described, *"rather than a toll gate in front of a stranger"*. Somebody
 * who has filled in a seating chart is not a stranger.
 *
 * **Each vendor's own button, because neither mark may be drawn by us.** These
 * were a matched pair of our own pills reading "Continue with Apple" and
 * "Continue with Google" in Hanken Grotesk, with no logo on either — and the
 * logo is not decoration here. Apple's guidelines permit a custom button only
 * when it carries *the official logo asset*, and Google's G is four exact
 * colours in an exact geometry. There is no SVG or icon library in this app and
 * no licensed artwork in the repo, so hand-drawing either would be a trademark
 * rendered wrong, which is worse than no logo at all.
 *
 * **Apple's button is Apple's.** `AppleAuthenticationButton` is the real
 * `ASAuthorizationAppleIDButton`: it draws the mark correctly, is localised and
 * accessible, and is guaranteed compliant. `cornerRadius` pills it to this
 * system's shape, which is the one style change Apple sanctions. What we own is
 * the box — height and width, so it stands level with the one below it.
 *
 * **Google's button was Google's for one build, and drew no logo at all.**
 * `GoogleSigninButton` renders `com.google.android.gms.common.SignInButton` on
 * Android — Play services' *deprecated* widget — and its artwork comes from
 * whichever GMS version happens to be on the device rather than from us or from
 * the npm package. On current ones that is a plain button with no G, and there
 * is no prop to change it: `setSize`, `setColor` and `setDisabled` are the
 * whole surface the view manager exposes. Reported from a phone, reverted, and
 * written down here so the same bet is not placed twice.
 *
 * So Google's is ours again, which also restores the matched pair — and it
 * carries the real G. **The artwork is Google's own, not a reproduction.**
 * Their guidelines forbid recreating the logo, and their branding page now
 * embeds it as markup with nothing to download, so it came from the place it
 * was always going to be correct: `GoogleSignIn.pod`'s own
 * `Sources/Resources/google@Nx.png`, which is the file `GIDSignInButton` draws
 * with. Verified by decoding rather than by eye — all four brand colours
 * (#EA4335, #4285F4, #FBBC05, #34A853) at 18pt, which is also the icon size
 * Google's own button spec asks for.
 *
 * Neither is styled as primary. Apple's rule forbids making its option less
 * prominent, and beyond the rule there is no reason to steer: whichever account
 * a person already has is the one that will work first time.
 *
 * Apple is absent rather than disabled on Android, and that is the module's
 * doing rather than ours — `expo-apple-authentication` has no Android
 * implementation. `appleAvailable` comes from `isAvailableAsync`, which also
 * answers false on an iOS version or a simulator that cannot do it, so a button
 * that would throw when tapped never renders.
 *
 * ---
 *
 * **Centred, as one group.** The architect's call on 2026-08-20, reversing
 * mine. `7c46b74` pushed the framing to the top and the ways in to the bottom
 * and argued that centring "put the one thing to tap in the middle of the
 * screen with 340pt of nothing either side, which reads as a screen that failed
 * to load".
 *
 * That was a fair description of what had been tried and a wrong conclusion
 * about centring. What was centred then was a *container* whose children were
 * still pushed to its two ends — so the button really was alone in the middle,
 * because the group had never been made into a group. Gathered as one block —
 * name, promise, offer, then the ways in 48 below them — the button is the base
 * of a composition rather than a control adrift in a void, and the emptiness
 * moves to the top and bottom margins where it belongs on a screen this short.
 *
 * The heading matches `TablePlan`'s opening question in size, because the plan
 * and this are two states of one screen rather than two screens.
 *
 * **A separate decision, and it still stands: nothing else may go in the
 * middle.** Three things were tried there and all three were removed by the
 * architect — the seated chairs read back (taken for the panel on sight, which
 * is what `plan.ts` keeps on the server), a standalone app icon (about the
 * company, on the one screen that is about the product), and a drawing of the
 * table. That ruling is about *content*, not about composition, and conflating
 * the two is how the anchored layout came to be defended as though somebody
 * else had chosen it. The words and the two controls may sit in the middle. A
 * fourth thing may not.
 *
 * **The mark is not that fourth thing, and the difference is the design.** The
 * architect asked for it on 2026-08-20, having removed the icon from this same
 * screen a fortnight earlier, and the two requests are not in conflict: an icon
 * alone at hero scale is a screen about the company, and a mark set beside the
 * word "Flintroom" at the word's own size is a logotype. It lives in the
 * lockup, at `labelLg`, above the headline rather than instead of it — so it
 * signs the screen without becoming its subject. Draw it larger and the earlier
 * objection comes back.
 *
 * **The back control is outside the group and stays at the top.** It belongs
 * against the safe area where a native one would be, and it is also outside the
 * scroll view, so it does not travel when a large Dynamic Type size makes the
 * block taller than the screen.
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
  /**
   * Opens one of the legal pages — sign-in-wrap, the agreement placed with
   * the buttons that create the account. A callback rather than `Linking`
   * imported here, so a test can see which page a press asked for.
   */
  onOpenLegal: (url: string) => void;
}

export function SignInSheet({
  appleAvailable,
  busy,
  refusal,
  onApple,
  onGoogle,
  onBack,
  onOpenLegal,
}: SignInSheetProps) {
  return (
    <View style={styles.sheet}>
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

      {/*
        **Scrollable, and invisible when it does not need to be.** `flexGrow: 1`
        makes the content fill the viewport, so the group still centres in it
        exactly as it would in a plain View. What it adds is a floor under the
        one failure that locks somebody out of the product: at the large Dynamic
        Type sizes a three-line headline becomes six, and this was a fixed
        column — the buttons left the bottom of the screen with nothing to
        scroll and no way to sign in.

        Bouncing is off because that is normally scrolling nothing: a front door
        that rubber-bands with no content below it reads as a list that failed
        to load the rest of itself.
      */}
      <ScrollView
        testID="sheet"
        style={styles.scroll}
        contentContainerStyle={styles.content}
        alwaysBounceVertical={false}
      >
        {/*
          **The front door's copy, not the survey's.** This read "Keep this
          room" / "Sign in to keep this plan" for as long as it sat *after* five
          questions, where "this plan" pointed at something on the screen behind
          it. Sign-in moved in front of the survey on 2026-08-20 and the words
          did not, so the first thing anybody saw referred to a plan that did
          not exist. Reported as "the sign in page is too basic": it was not
          basic so much as addressed to somebody who was not there.

          The name, then what the product does, then the instruction. Nothing
          else — this screen is crossed in a few seconds on the way to a
          provider sheet, and it does not need to hold anybody.

          **And no offer of free minutes, which is the second half of the same
          defect.** This read "Your first 15 minutes in the room are on us" —
          true of a stranger and false of everybody else. The grant is lifetime
          and once per account ever: `_ensure_free_minutes` runs on every
          sign-in path and is idempotent, so a returning user signing in here is
          promised something they were given long ago and will not be given
          again. Since #86 this screen is the signed-out launch gate, so it is
          crossed by reinstalls and expired tokens as much as by strangers —
          and being pre-auth, it has no account to ask which it is looking at.

          The offer belongs where it is true, and it is already there:
          `TablePlan` says "15 minutes in the room, on us", and only an account
          that has never described a room is ever routed to it. One screen
          later, beside the thing being given, per §4.6.
        */}
        <View style={styles.lockup}>
          {/* Hidden from assistive technology rather than labelled. The word is
              right beside it and says the same thing — announcing both makes
              the lockup stutter, "image, Flintroom, Flintroom". Both platforms
              need telling: iOS reads `accessibilityElementsHidden`, Android
              reads `importantForAccessibility`. */}
          <Image
            testID="mark"
            source={MARK_SOURCE}
            style={styles.mark}
            resizeMode="contain"
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            accessibilityIgnoresInvertColors
          />
          <Text style={styles.brand}>Flintroom</Text>
        </View>
        <Text style={styles.title} accessibilityRole="header">
          The room that grills you before the room that matters.
        </Text>
        <Text style={styles.body}>Sign in to begin.</Text>

        <View style={styles.ways}>
          {/* A tap used to produce one visible effect: the button faded to 40%.
              Between the provider's sheet closing and the route replacing, this
              screen sits on a round trip to our server and said nothing about
              it.

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

          {/* Its own group, one interval further down. A status line and a
              button are not siblings — held at the button spacing, "Signing you
              in…" read as a third item in the stack rather than as a caption on
              it. */}
          <View style={styles.stack}>
            {appleAvailable && (
              <AppleAuthenticationButton
                testID="apple-way"
                accessibilityLabel="Continue with Apple"
                accessibilityState={{ disabled: busy }}
                buttonType={AppleAuthenticationButtonType.CONTINUE}
                buttonStyle={AppleAuthenticationButtonStyle.WHITE_OUTLINE}
                cornerRadius={WAY / 2}
                // No `disabled` prop on this one, so the lock is the handler.
                // A button that does nothing beats a second sign-in resolving
                // against a session the first already established.
                onPress={busy ? () => undefined : onApple}
                style={[styles.way, busy && styles.dim]}
              />
            )}
            <Way
              label="Continue with Google"
              mark={GOOGLE_G}
              markTestID="google-mark"
              busy={busy}
              onPress={onGoogle}
            />
          </View>

          {/*
            The agreement, with the act it governs. A checkbox was considered
            and rejected 2026-08-28 — friction on the most fragile screen for
            no added enforceability in this class of app; the recording
            disclosure remains the separate, stronger consent where it
            matters, ahead of the microphone.
          */}
          <Text style={styles.agree}>
            By continuing, you agree to our{' '}
            <Text
              style={styles.agreeLink}
              accessibilityRole="link"
              onPress={() => onOpenLegal('https://www.flintroom.app/terms')}
            >
              Terms of Service
            </Text>
            {' '}and{' '}
            <Text
              style={styles.agreeLink}
              accessibilityRole="link"
              onPress={() => onOpenLegal('https://www.flintroom.app/privacy')}
            >
              Privacy Policy
            </Text>
            .
          </Text>
        </View>
      </ScrollView>
    </View>
  );
}

/**
 * Our own button, which today is Google's and tomorrow may be both.
 *
 * The leading edge is where the official G goes once the asset is in the repo —
 * an `Image` at the label's own scale, exactly as the mark sits beside the
 * wordmark above. Nothing is stubbed for it here: a placeholder square would be
 * a logo drawn wrong, and drawing it wrong is the thing being avoided.
 */
function Way({
  label,
  mark,
  markTestID,
  busy,
  onPress,
}: {
  label: string;
  /** The vendor's own artwork, as a bundled asset id. Never one we drew. */
  mark: number;
  markTestID: string;
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
      style={({ pressed }) => [styles.way, styles.pill, pressed && styles.pressed, busy && styles.dim]}
    >
      {/* Hidden from assistive technology, like the mark in the lockup: the
          label beside it already says whose button this is, and announcing
          both makes it stutter. */}
      <Image
        testID={markTestID}
        source={mark}
        style={styles.wayMark}
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
        accessibilityIgnoresInvertColors
      />
      <Text style={styles.wayLabel}>{label}</Text>
    </Pressable>
  );
}

const CHEVRON = 10;

/**
 * The height both vendor buttons are given, and the only number we set on them.
 *
 * 48 is `GIDSignInButton`'s own metric and comfortably over the 44pt touch
 * floor. Apple's button has no intrinsic size at all — its documentation is
 * explicit that without an explicit width and height it does not appear on
 * screen — so this is load-bearing rather than cosmetic there.
 */
const WAY = 48;

/**
 * The mark, at the size the wordmark beside it wants.
 *
 * The asset and its measured framing live in `lib/brand/mark.ts` now — the top
 * bar draws the same logo, and two copies of a measured constant is how two
 * lockups come to disagree about the size of one mark. 40 reads as a 21.6pt
 * mark, which sits *with* a 14pt label rather than over it.
 */
const MARK = 40;

/**
 * Google's G, at the size Google's own button spec asks for.
 *
 * 18pt, and the file is 18×18 with its mark filling the canvas edge to edge —
 * so unlike our own mark there is no framing to solve for and the drawn size is
 * the read size. `@2x` and `@3x` sit beside it and Metro picks the density.
 */
const GOOGLE_MARK = 18;
const GOOGLE_G = require('../../../assets/brand/google-g.png');

const styles = StyleSheet.create({
  sheet: { flex: 1 },
  scroll: { flex: 1 },
  /**
   * One centred group, with the emptiness at the top and bottom rather than
   * between two halves of the composition.
   *
   * `justifyContent: 'center'` with `flexGrow: 1` is the whole of it: the
   * content view fills the viewport when the words fit, so the block sits in
   * the middle; when they do not, `flexGrow` stops holding it there and the
   * ScrollView takes over from the top. There is no `flex: 1` here on purpose
   * — that would cap the content at the viewport and clip the overflow it
   * exists to let through.
   *
   * `paddingVertical` rather than a `paddingTop` and `paddingBottom` that
   * differ: an off-centre group on a screen that is deliberately centred reads
   * as a mistake, not as an optical correction.
   */
  content: {
    flexGrow: 1,
    justifyContent: 'center',
    paddingHorizontal: space.screen,
    paddingVertical: space.loose,
  },

  /**
   * The bottom end, in two groups rather than one.
   *
   * Everything here used to sit at a single 12, which said the status line and
   * the buttons were siblings. They are not — "Signing you in…" is a caption on
   * the thing below it, and at the button spacing it read as a third item in
   * the stack. 16 to the group, 12 within it.
   */
  ways: { gap: space.base, marginTop: space.major },
  stack: { gap: space.snug },

  /**
   * Outside the centred group and outside the scroll view.
   *
   * A back control belongs against the safe area at the leading edge, which is
   * where a native one sits — centring it with the words would put it halfway
   * down the screen, and leaving it inside the scroll view would send it off
   * the top the moment a large type size made the block taller than the screen.
   * Its own left margin, because it no longer inherits the content's padding.
   */
  back: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: space.tight,
    minHeight: 44,
    marginLeft: space.screen,
    marginTop: space.tight,
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

  /**
   * Quiet, above the promise: a name earns less space than what it does.
   *
   * These three margins are the lede's whole rhythm, and it used to run
   * backwards. A container `gap` of 16 plus this 8 put *24* between the name
   * and the sentence saying what the name does — the tightest pair on the
   * screen — while the larger break, from that sentence to the offer, got 16.
   * It steps out now: 8, then 12, and the three lines read as one block with
   * the void below them rather than as three stacked lines.
   */
  /**
   * Mark and word on one line, centred as a unit.
   *
   * A row rather than the mark stacked above the word: stacked, it becomes the
   * tallest thing above the headline and starts competing with it, which is the
   * standalone-icon objection arriving by a different route.
   */
  lockup: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.tight,
    marginBottom: space.tight,
  },
  // Pulled back to the ink — see `padFor`. Without it the 8pt gap to the
  // wordmark reads as 19.
  mark: { width: MARK, height: MARK, marginHorizontal: -padFor(MARK) },
  brand: { ...type.labelLg, color: color.primary },
  title: {
    ...type.headlineLg,
    color: color.onSurface,
    textAlign: 'center',
    marginBottom: space.snug,
  },
  body: { ...type.bodyLg, color: color.onSurfaceVariant, textAlign: 'center' },
  agree: {
    ...type.bodySm,
    color: color.onSurfaceVariant,
    textAlign: 'center',
    marginTop: space.loose,
  },
  agreeLink: { color: color.primary },

  /**
   * The box, and nothing about the button inside it.
   *
   * No `backgroundColor` and no `borderRadius`: Apple's documentation says in
   * as many words that setting either through `style` will not work and is
   * against the App Store guidelines — the sanctioned controls are the
   * `buttonStyle` and `cornerRadius` props, which is where the pill comes from.
   * Height and width are ours because neither vendor's button fills a column on
   * its own, and equal boxes are what keeps them equally prominent.
   */
  way: { height: WAY, width: '100%' },
  /**
   * Ours only, and never Apple's.
   *
   * Apple's documentation says in as many words that setting `backgroundColor`
   * or `borderRadius` through `style` will not work and is against the App
   * Store guidelines — its sanctioned controls are the `buttonStyle` and
   * `cornerRadius` props. So the fill and the shape live in a style only `Way`
   * wears, and `way` above stays the box both of them share.
   */
  pill: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: color.onSurface,
  },
  // 12 between mark and label, which is what Google's button spec asks for.
  wayMark: { width: GOOGLE_MARK, height: GOOGLE_MARK, marginRight: space.snug },
  wayLabel: { ...type.labelLg, color: color.onSurface },
  pressed: { opacity: 0.6 },
  dim: { opacity: 0.4 },

  // Above the buttons rather than below them: a refusal that appears under the
  // control pushes nothing and is read after the second tap. Above, it lands
  // between the reason and the retry.
  refusal: { ...type.bodyMd, color: color.danger, textAlign: 'center' },
  // Not `danger`. Waiting is not a failure, and colouring it as one is how an
  // interface teaches people to distrust its own red.
  waiting: { ...type.bodyMd, color: color.onSurfaceVariant, textAlign: 'center' },
});
