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
      seated={['budget']}
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

it('shows the room they described, so "your panel is ready" is shown and not just claimed', async () => {
  await show({ seated: ['budget', 'ally'] });

  expect(screen.getByText('Controls the budget')).toBeTruthy();
  expect(screen.getByText('Already on your side')).toBeTruthy();
});

it('names nobody as an archetype', async () => {
  // The seats are the words the presenter chose. Turning them into the panel
  // here would pre-empt the reveal on setup and, worse, could disagree with
  // the room `composition.py` actually builds.
  await show({ seated: ['budget'] });

  expect(screen.queryByText(/CFO|Skeptic|Champion|archetype/i)).toBeNull();
});

it('says nothing about a table nobody sat at', async () => {
  await show({ seated: [] });

  expect(screen.queryByLabelText(/in chair/)).toBeNull();
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

it('points at the chairs it is showing rather than asserting a panel', async () => {
  // "Your panel is ready" claimed a thing the screen was not showing, in a
  // word nothing else on it used — the heading says room, the rows are chairs,
  // and Panel is reserved for the archetypes the server casts.
  await show({ seated: ['budget', 'ally'] });

  expect(screen.queryByText(/Your panel is ready/)).toBeNull();
  expect(screen.getByText(/chairs/i)).toBeTruthy();
});

it('does not promise filled chairs to somebody who filled none', async () => {
  await show({ seated: [] });

  expect(screen.queryByText(/chairs/i)).toBeNull();
  expect(screen.getByText(/15 minutes/)).toBeTruthy();
});
