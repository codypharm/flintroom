import { fireEvent, render, screen } from '@testing-library/react-native';

import { SignInSheet } from './SignInSheet';

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

  await render(
    <SignInSheet
      appleAvailable
      busy={false}
      refusal={null}
      onApple={onApple}
      onGoogle={onGoogle}
      onBack={onBack}
      {...over}
    />
  );

  return { onApple, onGoogle, onBack };
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
  // Apple's own rule forbids making its option less prominent, and there is no
  // reason to steer anyway: whichever account somebody already has is the one
  // that works first time. Same styles, so neither reads as the primary.
  await show();

  const [apple, google] = [
    screen.getByLabelText('Continue with Apple'),
    screen.getByLabelText('Continue with Google'),
  ];

  expect(JSON.stringify(apple.props.style)).toBe(JSON.stringify(google.props.style));
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

it('offers the minutes rather than counting them', async () => {
  await show();

  expect(screen.getByText(/first 15 minutes in the room/)).toBeTruthy();
  expect(screen.queryByText(/remaining|left|of 15/i)).toBeNull();
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
  await show();

  expect(screen.getByText(/Sign in to keep this plan/)).toBeTruthy();
  expect(screen.queryByText(/Your panel is ready/)).toBeNull();
});

it('puts nothing in the middle of the screen', async () => {
  // Three things were tried there and all three were removed: the plan read
  // back, the app icon, and a drawing of the table. What is left is the heading,
  // the sentence, and the ways in — and the test exists so the next good idea
  // has to be argued for rather than slipped in.
  await show();

  expect(screen.queryAllByTestId('chair-mark', { includeHiddenElements: true }))
    .toHaveLength(0);
  expect(screen.queryByRole('image')).toBeNull();
});
