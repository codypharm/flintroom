import { StyleSheet } from 'react-native';

import { color } from '../../theme/tokens';

import { render, screen, userEvent } from '@testing-library/react-native';
import { SafeAreaProvider, type Metrics } from 'react-native-safe-area-context';

import { TopBar, type TopBarProps } from './TopBar';

/**
 * The bar every top-level screen wears.
 *
 * Asked for three times before it was heard: *"are you sure we do not need a
 * header in this app"*, then *"what of the header"*, then *"i mean proper
 * header as in whatsapp, linkedin app and the mockup design"*. The first two
 * were answered as though they were about back buttons on pushed screens. They
 * were not — and `design-guide/profile/code.html:206` labels the thing they
 * were about **"TopAppBar (Shared Component)"**, on a bar that appears in nine
 * of the eleven screen mockups.
 */

/**
 * The bar is handed to a navigator as its `header`, so it is the topmost thing
 * on the screen and owns the status-bar inset itself. That means a real
 * provider here — `initialMetrics` is how the library supplies one off-device,
 * and a notch-sized inset is the case worth drawing against.
 */
const NOTCHED: Metrics = {
  frame: { x: 0, y: 0, width: 393, height: 852 },
  insets: { top: 59, left: 0, right: 0, bottom: 34 },
};

function show(props: TopBarProps) {
  return render(
    <SafeAreaProvider initialMetrics={NOTCHED}>
      <TopBar {...props} />
    </SafeAreaProvider>
  );
}

it('carries the product, on every screen that wears it', async () => {
  await show({ held: null });

  expect(screen.getByText('Flintroom')).toBeTruthy();
  expect(screen.getByTestId('mark', { includeHiddenElements: true })).toBeTruthy();
});

it('does not read the mark out beside the word it already is', async () => {
  // Same rule as the sign-in lockup: the word says it, so the picture must not
  // say it again into a screen reader.
  await show({ held: null });

  const mark = screen.getByTestId('mark', { includeHiddenElements: true });

  expect(mark.props.accessibilityElementsHidden).toBe(true);
  expect(mark.props.importantForAccessibility).toBe('no-hide-descendants');
});

it('holds the time in the room where the mockup puts the token pill', async () => {
  // The mockups put "120 Tokens" in this slot. The slot is layout and it stays;
  // the content is retired twice over — the token economy went to minutes, and
  // `CLAUDE.md` forbids a depleting counter outright.
  await show({ held: { minutes: 55, any: true } });

  expect(screen.getByLabelText('You have 55 minutes')).toBeTruthy();
});

it('never counts down, whatever the balance says', async () => {
  await show({ held: { minutes: 3, any: true } });

  expect(screen.queryByText(/remaining|left|available|of \d/i)).toBeNull();
  expect(screen.queryByText(/token/i)).toBeNull();
});

it('draws the bar before the balance arrives, rather than jumping', async () => {
  // The balance is a round trip and the bar is pinned. Reserving nothing would
  // make every cold start pop a chip in beside the wordmark a beat later.
  await show({ held: null });

  expect(screen.getByText('Flintroom')).toBeTruthy();
  expect(screen.queryByLabelText(/minutes in the room/)).toBeNull();
});

it('sits the time on the wordmark line, not against the top of the bar', async () => {
  // Reported from a phone: "the remaining time is close to the top".
  //
  // `TimeInTheRoom` declared `alignSelf: 'flex-start'` on its chip, and a
  // child's `alignSelf` overrides its parent's `alignItems`. In the column it
  // was written for — stacked above the control that spends the minutes — the
  // cross axis is horizontal and that meant "do not stretch across the screen".
  // In this bar the cross axis is vertical, so the very same declaration means
  // "pin to the top", and the bar's own `alignItems: 'center'` was powerless.
  //
  // The fix is not a counter-alignment here. A component that hard-codes its
  // placement inside a parent it cannot see is the defect; the container owns
  // where its children sit, so the chip stopped saying.
  await show({ held: { minutes: 55, any: true } });

  const chip = StyleSheet.flatten(
    screen.getByLabelText('You have 55 minutes').props.style
  ) as { alignSelf?: string };

  expect(chip.alignSelf).toBeUndefined();
});

it('sits on its own plane rather than sharing the content ground', async () => {
  // Asked for as "a slight different color". Flat-on-the-same-ground is what
  // the mockups draw and what this shipped as, and on a phone it read as no bar
  // at all — the wordmark just floated above the screen's first line.
  //
  // Asserted as a relationship, not a hex: the bar must not be the ground. A
  // test naming the colour would have to be edited every time the palette
  // moves, and would still pass if both were changed to the same new value.
  await show({ held: null });

  const bar = StyleSheet.flatten(
    screen.getByTestId('bar').props.style
  ) as { backgroundColor?: string };

  expect(bar.backgroundColor).toBeTruthy();
  expect(bar.backgroundColor).not.toBe(color.surface);
});

it('says whose the minutes are, not just how many there are', async () => {
  // Reported from a phone: "the text 54 mins in the room is not informative".
  // It is not — "55 minutes in the room" can be read three ways. How long a
  // room lasts. How long you have been in one. What you hold. Only the third
  // is true, and the chip sits in a bar on every screen where none of the
  // other two would even make sense.
  //
  // "You have" is what fixes it, and it is the one word §4.6 leaves open. The
  // four it forbids — available, remaining, left, of your allowance — are the
  // depleting counter arriving one adjective at a time. A possessive says the
  // opposite: these are held, not draining.
  await show({ held: { minutes: 55, any: true } });

  expect(screen.getByText(/You have/)).toBeTruthy();
  expect(screen.queryByText(/remaining|left|available|allowance/i)).toBeNull();
});

it('takes a tap on the time to where more of it is sold', async () => {
  // The chip is the one place the balance is always visible, and it was inert
  // text — the only doors to the buy screen were Settings and a room that
  // refused to open. The fact you tap is the fact the screen answers.
  const onTime = jest.fn();
  await show({ held: { minutes: 55, any: true }, onTime });

  await userEvent.press(screen.getByLabelText('You have 55 minutes'));

  expect(onTime).toHaveBeenCalled();
});

it('keeps the chip a statement where no destination is wired', async () => {
  // Without a handler the chip stays what it always was — a fact, not a
  // button — so a screen that renders the bar bare does not grow a control
  // that goes nowhere.
  await show({ held: { minutes: 55, any: true } });

  expect(screen.getByLabelText('You have 55 minutes').props.accessibilityRole).toBe('text');
});
