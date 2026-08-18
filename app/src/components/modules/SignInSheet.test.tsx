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

  await render(
    <SignInSheet
      appleAvailable
      busy={false}
      refusal={null}
      onApple={onApple}
      onGoogle={onGoogle}
      {...over}
    />
  );

  return { onApple, onGoogle };
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
