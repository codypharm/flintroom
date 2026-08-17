import { render, screen, userEvent } from '@testing-library/react-native';

import { RecordingDisclosure } from './RecordingDisclosure';

/**
 * The sheet that makes on-by-default defensible.
 *
 * `docs/session-retention.md` chose disclosure over opt-in on the grounds that
 * what stores require for a recording somebody is themselves making is
 * disclosure and control. Both halves have to actually be here — the claim is
 * not "we showed a sheet", it is that the sheet said the true things.
 *
 * Tested on what it says and does rather than how it looks, so the visual pass
 * can change everything about it without touching this file.
 */

type Props = Parameters<typeof RecordingDisclosure>[0];

/**
 * `render` is awaited because it is asynchronous in
 * `@testing-library/react-native` v14 — it returns a promise, and a test that
 * forgets leaves `screen` empty with the misleading complaint that render was
 * never called. This is the project's first component test, so nothing had hit
 * that yet.
 */
async function show(props: Partial<Props> = {}) {
  await render(
    <RecordingDisclosure retentionDays={30} onContinue={jest.fn()} {...props} />
  );
}

it('says the room is recorded, in words rather than by implication', async () => {
  await show();

  expect(await screen.findByText(/saved/i)).toBeOnTheScreen();
});

it('states how long a room is kept, using the account’s own window', async () => {
  /**
   * The number is per tier and comes from the server, so a hard-coded "30 days"
   * would be a lie to every paying user — which is the worst possible place for
   * one, since this is the screen whose only job is being true.
   */
  await show({ retentionDays: 365 });

  expect(screen.getByText(/365 days/)).toBeOnTheScreen();
});

it('says the microphone is needed and why, before the system asks', async () => {
  /**
   * `docs/onboarding.md`: an iOS denial is sticky, so the prompt appears where
   * its reason is self-evident. This sheet is that reason — the OS dialog
   * follows it, never precedes it.
   */
  await show();

  expect(screen.getByText(/microphone/i)).toBeOnTheScreen();
});

it('names where saving can be turned off', async () => {
  /**
   * The control is the other half of the decision. A disclosure that mentions
   * no way out is the version stores treat as consent theatre, and
   * `docs/session-retention.md` promises this sentence explicitly.
   */
  await show();

  expect(screen.getByText(/settings/i)).toBeOnTheScreen();
});

it('continues only when the person acts', async () => {
  const onContinue = jest.fn();
  await show({ onContinue });

  expect(onContinue).not.toHaveBeenCalled();

  await userEvent.press(screen.getByRole('button'));

  expect(onContinue).toHaveBeenCalledTimes(1);
});

it('offers one action, so there is nothing to mistake for a refusal', async () => {
  /**
   * Recording is on by default and this sheet does not toggle it — the control
   * lives in Settings, per the decision. A second button here would read as
   * "decline", and a decline that silently did not change anything is worse
   * than not offering one.
   */
  await show();

  expect(screen.getAllByRole('button')).toHaveLength(1);
});
