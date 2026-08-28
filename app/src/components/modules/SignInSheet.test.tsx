import { StyleSheet, Text, TouchableOpacity } from 'react-native';

import { fireEvent, render, screen, userEvent } from '@testing-library/react-native';

import { SignInSheet } from './SignInSheet';

/*
 * Both vendors' own buttons, stubbed.
 *
 * They are native views — `ASAuthorizationAppleIDButton` and `GIDSignInButton`
 * — so under the test renderer they draw nothing and report nothing. The stubs
 * stand in at exactly the surface this component uses: a press, a disabled
 * state, and a testID to find them by. What they draw is Apple's and Google's
 * business, which is the entire reason for using them.
 */
// `mock`-prefixed, which is the one way a factory may reach a value defined
// outside it: Babel hoists `jest.mock` above the imports, and everything else
// would be read before it exists.
const MockTouch = TouchableOpacity;
const MockLabel = Text;

jest.mock('expo-apple-authentication', () => ({
  AppleAuthenticationButtonType: { SIGN_IN: 0, CONTINUE: 1, SIGN_UP: 2 },
  AppleAuthenticationButtonStyle: { WHITE: 0, WHITE_OUTLINE: 1, BLACK: 2 },
  AppleAuthenticationButton: (props: Record<string, unknown>) => (
    <MockTouch {...props}>
      <MockLabel>Continue with Apple</MockLabel>
    </MockTouch>
  ),
}));

// Google's button is not mocked, because Google's button is not used. See
// `offers Apple its own button, and draws Google's ourselves`.

/**
 * The one screen in this product that a stranger sees before deciding anything.
 *
 * The rules worth holding: Apple never renders where it cannot work, neither
 * option is steered toward, and a cancelled sheet is not dressed up as a
 * failure.
 */

async function show(over: Partial<Parameters<typeof SignInSheet>[0]> = {}) {
  const onApple = jest.fn();
  const onGoogle = jest.fn();
  const onBack = jest.fn();

  const drawn = await render(
    <SignInSheet
      appleAvailable
      busy={false}
      refusal={null}
      onApple={onApple}
      onGoogle={onGoogle}
      onBack={onBack}
      onOpenLegal={() => undefined}
      {...over}
    />
  );

  // The render result as well as the mocks, so a test can ask what is actually
  // on the page. `screen` cannot, and the query that pretended to —
  // `queryByRole('image')` — matches nothing at all: React Native's `Image`
  // publishes no implicit role, so that assertion passed whether or not an
  // image was drawn. It guarded this screen for two commits while guarding
  // nothing, which is the failure mode of asserting an absence.
  return { ...drawn, onApple, onGoogle, onBack };
}

/** How many `<Image>` the screen actually drew, off the public render tree. */
function images(tree: unknown): number {
  if (Array.isArray(tree)) return tree.reduce<number>((n, c) => n + images(c), 0);
  if (tree === null || typeof tree !== 'object') return 0;
  const node = tree as { type?: string; children?: unknown };
  return (node.type === 'Image' ? 1 : 0) + images(node.children);
}

it('offers both ways in when the device can do both', async () => {
  await show();

  expect(screen.getByLabelText('Continue with Apple')).toBeTruthy();
  expect(screen.getByLabelText('Continue with Google')).toBeTruthy();
});

it('does not render Apple where it cannot work', async () => {
  // Android, an old iOS, or a simulator with no Apple ID. A button that throws
  // when tapped is worse than one that was never offered — and on Android
  // Google is the only way in, so nothing else may be at risk from this.
  await show({ appleAvailable: false });

  expect(screen.queryByLabelText('Continue with Apple')).toBeNull();
  expect(screen.getByLabelText('Continue with Google')).toBeTruthy();
});

it('steers toward neither', async () => {
  // Apple's rule forbids making its option less prominent, and there is no
  // reason to steer anyway: whichever account somebody already has is the one
  // that works first time.
  //
  // This used to compare the two style objects and demand they be identical.
  // That stopped being the right assertion when each button became its vendor's
  // own — Apple's and Google's buttons are *supposed* to look like themselves,
  // and Apple's guidelines govern prominence rather than sameness. What has to
  // hold is that they occupy the same box: same height, both full width, so
  // neither reads as the primary and the second is not a footnote under the
  // first.
  await show();

  const box = (label: string) =>
    StyleSheet.flatten(screen.getByLabelText(label).props.style) as {
      height?: number;
      width?: string | number;
    };

  expect(box('Continue with Apple').height).toBe(box('Continue with Google').height);
  expect(box('Continue with Apple').width).toBe(box('Continue with Google').width);
});

it('offers Apple its own button, and draws Googles ourselves', async () => {
  // Reported from a phone: "i am not seeing logo in the google buton".
  //
  // `GoogleSigninButton` was the wrong bet and this test records why, so it is
  // not made again. On Android it renders
  // `com.google.android.gms.common.SignInButton` — Google Play services'
  // *deprecated* widget — and its artwork comes from whichever GMS version is
  // on the device, not from us or from the npm package. On current ones that is
  // a plain button with no G, and no prop reaches it: `setSize`, `setColor` and
  // `setDisabled` are the entire surface the view manager exposes. Nothing
  // could have been styled around it.
  //
  // So Google's button is ours again, which also restores the matched pair.
  // Apple's stays native: `ASAuthorizationAppleIDButton` draws its own mark
  // correctly, is guaranteed compliant, and Apple's guidelines prefer it.
  //
  // The G itself is still missing and cannot be invented here — Google's
  // branding guidelines say in as many words not to recreate the logo, and it
  // is four exact colours in an exact geometry. It needs the official asset in
  // the repo.
  await show();

  expect(screen.getByTestId('apple-way')).toBeTruthy();
  expect(screen.queryByTestId('google-way')).toBeNull();
  expect(screen.getByLabelText('Continue with Google').props.accessibilityRole)
    .toBe('button');
});

it('locks both while one is in flight', async () => {
  // Two sheets at once is two sign-ins, and the second would arrive against a
  // session the first already established.
  const { onApple, onGoogle } = await show({ busy: true });

  fireEvent.press(screen.getByLabelText('Continue with Apple'));
  fireEvent.press(screen.getByLabelText('Continue with Google'));

  expect(onApple).not.toHaveBeenCalled();
  expect(onGoogle).not.toHaveBeenCalled();
});

it('says a refusal out loud rather than only colouring it', async () => {
  // An alert role, because somebody using a screen reader must hear that the
  // thing they just tapped did not work.
  await show({ refusal: 'We could not reach the server.' });

  expect(screen.getByRole('alert')).toBeTruthy();
});

it('promises nothing it cannot know about whoever is standing there', async () => {
  // Reported from a phone: "why does it always say sign in to begin your first
  // 15 mins, that is not right for all users". It is not.
  //
  // The grant is lifetime and once per account ever — `_ensure_free_minutes`
  // runs on every sign-in path and is idempotent inside `LedgerService`, so a
  // returning user signing in gets nothing (`docs/onboarding.md`, "The free
  // grant is bound to sign-in, not to finishing onboarding"). And this screen
  // is pre-auth: since #86 it is the signed-out launch gate, crossed by
  // strangers, by people who reinstalled, and by people whose token expired,
  // with no way to tell them apart. There is no account to ask.
  //
  // So the offer moves to where it is true. `TablePlan` already says "15
  // minutes in the room, on us", and only an account that has never described a
  // room is ever routed there — one screen later, beside the thing being given.
  //
  // This is the same defect as `claims nothing it is not showing` below, which
  // fixed the half of the sentence that pointed at a plan nobody had made and
  // left the half that promises minutes nobody may be owed.
  await show();

  expect(screen.getByText(/Sign in to begin/)).toBeTruthy();
  expect(screen.queryByText(/15 minutes|on us|free/i)).toBeNull();
});

it('lets somebody go back to the plan they just filled in', async () => {
  // The plan and this sheet are two states of one screen, and until now the
  // second had no way back to the first — a back gesture left onboarding
  // entirely, abandoning five answers that were never posted anywhere.
  const { onBack } = await show();

  fireEvent.press(screen.getByLabelText('Back to your plan'));

  expect(onBack).toHaveBeenCalled();
});

it('does not let the plan be reopened while sign-in is in flight', async () => {
  // Going back mid-request would leave a sign-in resolving against a screen
  // that has moved on, and the plan it posted already left the building.
  const { onBack } = await show({ busy: true });

  fireEvent.press(screen.getByLabelText('Back to your plan'));

  expect(onBack).not.toHaveBeenCalled();
});

it('says something while a sign-in is in flight', async () => {
  // The only sign a tap had registered was the button dimming. Between the
  // provider sheet closing and the route replacing, this screen sits on a
  // round trip to our server saying nothing at all.
  await show({ busy: true });

  expect(screen.getByText(/Signing you in/)).toBeTruthy();
});

it('does not announce progress as an error', async () => {
  // `alert` is for the refusal. A live region announces the wait without
  // interrupting, which is the difference between "hold on" and "it failed".
  await show({ busy: true });

  expect(screen.queryByRole('alert')).toBeNull();
});

it('says nothing about waiting when nothing is in flight', async () => {
  await show();

  expect(screen.queryByText(/Signing you in/)).toBeNull();
});

it('reads the plan back to nobody', async () => {
  // The seated chairs were drawn here for one build. They were removed because
  // the first person to see them read them as the panel — which is precisely
  // what `plan.ts` keeps on the server, and what the reveal on setup is for.
  // Anything resembling a cast list on this screen spends that early.
  await show();

  expect(screen.queryByText(/Controls the budget|chairs|panel/i)).toBeNull();
  expect(screen.queryByLabelText(/in chair/)).toBeNull();
});

it('claims nothing it is not showing', async () => {
  // The intent is unchanged and the words are not. This read "Sign in to keep
  // this plan" while the sheet sat *after* five questions, where "this plan"
  // pointed at something on the screen behind it. Sign-in moved in front of the
  // survey on 2026-08-20, and a promise about a plan nobody has made yet is
  // exactly the claim this test exists to forbid.
  await show();

  expect(screen.getByText(/Sign in to begin/)).toBeTruthy();
  expect(screen.queryByText(/this plan/i)).toBeNull();
  expect(screen.queryByText(/Your panel is ready/)).toBeNull();
});

it('says what the product is, on the first screen anybody sees', async () => {
  // Reported as "the sign in page is too basic". It was not basic so much as
  // addressed to somebody who was not there: the words assumed a survey had
  // just been answered. This is now the front door, so it says the name and
  // what the room is for before asking for anything.
  await show();

  expect(screen.getByText('Flintroom')).toBeTruthy();
  expect(screen.getByText(/grills you before the room that matters/)).toBeTruthy();
});

it('adds no picture to the group but the two marks that name things', async () => {
  // Renamed twice. "Nothing in the middle" reads as forbidding the centred
  // layout, and "nothing but the words" is no longer true now that the mark
  // sits beside the name.
  //
  // The ruling this guards was never about composition and is not repealed by
  // the mark: three *pieces of content* were tried here and all three were
  // removed — the plan read back, a standalone app icon, and a drawing of the
  // table. One image, and it is the one in the lockup. A second is the next
  // good idea being slipped in.
  //
  // Two images now, and both are logos: ours in the lockup, Google's on
  // Google's button. A third is a picture, and a picture is the thing that was
  // removed three times.
  const drawn = await show();

  expect(screen.queryAllByTestId('chair-mark', { includeHiddenElements: true }))
    .toHaveLength(0);
  expect(images(drawn.toJSON())).toBe(2);
});

it("puts Google's own artwork on Google's button", async () => {
  // The mark is `google@3x.png` and its siblings, lifted out of the GoogleSignIn
  // pod's own `Sources/Resources` — Google's SDK shipping Google's logo, which
  // is what `GIDSignInButton` draws with. Not recreated: their guidelines forbid
  // that, and the file carries all four brand colours (#EA4335, #4285F4,
  // #FBBC05, #34A853) at the exact geometry, verified by decoding it rather
  // than by looking at it.
  //
  // Copied into `assets/brand/` rather than referenced where it was found:
  // `ios/` is generated by `pod install` and gitignored, so a clean checkout
  // would have had a button pointing at nothing.
  await show();

  expect(screen.getByTestId('google-mark', { includeHiddenElements: true })).toBeTruthy();
});

it('sets the mark beside the name rather than standing it in the middle', async () => {
  // The architect asked for the mark on 2026-08-20, having removed a standalone
  // app icon from this screen earlier. Those are not the same request and the
  // difference is the whole design: an icon alone in the middle is a screen
  // about the company, and a mark at wordmark scale beside "Flintroom" is a
  // logotype. It goes in the lockup, at the label's size, not above the
  // headline at the headline's size.
  await show();

  expect(screen.getByTestId('mark', { includeHiddenElements: true })).toBeTruthy();
});

it('does not read the mark out beside the word it already is', async () => {
  // A screen reader announcing "image, Flintroom" and then "Flintroom" is the
  // lockup stuttering. The word carries the meaning; the mark is the same word
  // drawn, so it is hidden on both platforms rather than given a label.
  await show();

  const mark = screen.getByTestId('mark', { includeHiddenElements: true });

  expect(mark.props.accessibilityElementsHidden).toBe(true);
  expect(mark.props.importantForAccessibility).toBe('no-hide-descendants');
});

it('lets somebody reach the ways in when the words do not fit the screen', async () => {
  // The one failure on this screen that locks somebody out of the product
  // entirely. The sheet was a fixed `flex: 1` column pushed to both ends, so at
  // the large Dynamic Type sizes — where a three-line headline becomes six —
  // the buttons went off the bottom edge with nothing to scroll and no way to
  // sign in at all. `TablePlan`, the screen after this one, has always been a
  // ScrollView; this one was not.
  //
  // `flexGrow: 1` is what keeps the composition identical when the words do
  // fit: the container still fills the screen and still anchors both ends.
  await show();

  expect(screen.getByTestId('sheet').type).toBe('RCTScrollView');
});

it('gathers the words and the ways in as one group in the middle', async () => {
  // The architect's call, 2026-08-20, reversing mine. `7c46b74` anchored this
  // sheet to both ends and argued centring "put the one thing to tap in the
  // middle of the screen with 340pt of nothing either side". That critique was
  // of a centred *container* whose children were still pushed apart — the group
  // was never a group. Centred as one block, the button is the base of a
  // composition rather than a lone control in a void.
  await show();

  const content = StyleSheet.flatten(
    screen.getByTestId('sheet').props.contentContainerStyle
  );

  expect(content.justifyContent).toBe('center');
});

it('places the agreement where the account is created', async () => {
  // Sign-in-wrap: the line sits with the buttons that create the account, so
  // agreeing is part of the act it governs. A checkbox was considered and
  // rejected 2026-08-28 — friction on the most fragile screen, for no added
  // enforceability in this class of app.
  const opened: string[] = [];
  await show({ onOpenLegal: (url: string) => opened.push(url) });

  expect(screen.getByText(/By continuing, you agree/)).toBeOnTheScreen();

  await userEvent.press(screen.getByText('Terms of Service'));
  await userEvent.press(screen.getByText('Privacy Policy'));

  expect(opened).toEqual([
    'https://www.flintroom.app/terms',
    'https://www.flintroom.app/privacy',
  ]);
});
