import { fireEvent, render, screen, userEvent } from '@testing-library/react-native';

import { SettingsScreen, type Holdings } from './SettingsScreen';

/**
 * Settings, as the inventory of what Flintroom holds.
 *
 * The surface brief (`.impeccable/surfaces/app-src-app-settings-tsx.md`) leads
 * with what is held about the person rather than with a list of preference
 * nouns, and puts each control on the thing it governs. These tests are about
 * what the screen states and lets somebody do — the composition is the brief's
 * to change.
 */

const NOTHING: Holdings = {
  rooms: 0,
  oldestExpiry: null,
  materials: 0,
  recordsRooms: true,
  retentionDays: 30,
  minutesRemaining: 15,
};

async function show(holdings: Partial<Holdings> = {}, props = {}) {
  await render(
    <SettingsScreen
      holdings={{ ...NOTHING, ...holdings }}
      onRecordingChange={jest.fn()}
      onDeleteAccount={jest.fn()}
      {...props}
    />
  );
}

it('states plainly that nothing is held yet', async () => {
  /**
   * The empty state is most people's first sight of this screen, and the brief
   * is explicit that it must read as reassuring and factual. A screen that
   * showed "0" in a slot built for a number reads as a counter that failed, not
   * as an account with nothing in it.
   */
  await show();

  expect(screen.getByText(/no rooms saved/i)).toBeOnTheScreen();
});

it('says how many rooms are held and when the oldest goes', async () => {
  await show({ rooms: 4, oldestExpiry: new Date('2026-09-16T00:00:00Z') });

  expect(screen.getByText(/4 rooms/i)).toBeOnTheScreen();
  expect(screen.getByText(/16 September/i)).toBeOnTheScreen();
});

it('shows a date rather than a countdown', async () => {
  /**
   * "Until 16 September" is a fact; "12 days left" is a clock running down on
   * something the person did not ask to lose. The brief refuses urgency styling
   * on expiry for the same reason — the window elapsing is the promise being
   * kept, not a warning.
   */
  await show({ rooms: 1, oldestExpiry: new Date('2026-09-16T00:00:00Z') });

  expect(screen.queryByText(/days left|expires in|remaining/i)).not.toBeOnTheScreen();
});

it('puts the switch that stops recording on the rooms it governs', async () => {
  const onRecordingChange = jest.fn();
  await show({ rooms: 2 }, { onRecordingChange });

  // `fireEvent` rather than `userEvent.press`: a Switch reports through
  // `valueChange`, and pressing it does nothing a test can observe.
  fireEvent(screen.getByRole('switch'), 'valueChange', false);

  expect(onRecordingChange).toHaveBeenCalledWith(false);
});

it('says new rooms will not be saved when recording is off', async () => {
  await show({ recordsRooms: false });

  expect(screen.getByText(/not being saved/i)).toBeOnTheScreen();
});

it('still lists rooms already held when recording is off', async () => {
  /**
   * Turning it off stops future rooms; it does not delete past ones, because
   * they were made under a disclosure the person accepted. Hiding them here
   * would imply otherwise.
   */
  await show({ recordsRooms: false, rooms: 3 });

  expect(screen.getByText(/3 rooms/i)).toBeOnTheScreen();
});

it('shows time left in plain minutes and nothing finer', async () => {
  /**
   * §4.6 forbids a depleting counter. The server deliberately returns whole
   * minutes and a boolean — no seconds, no per-bucket split — and the screen
   * must not reintroduce the shape the API refused to send.
   */
  await show({ minutesRemaining: 15 });

  expect(screen.getByText(/15 minutes/i)).toBeOnTheScreen();
  expect(screen.queryByRole('progressbar')).not.toBeOnTheScreen();
});

it('asks before destroying an account', async () => {
  /**
   * Irreversible, and the one control on this screen that is. It must not be a
   * single tap next to reversible switches.
   */
  const onDeleteAccount = jest.fn();
  await show({}, { onDeleteAccount });

  await userEvent.press(screen.getByText(/delete account/i));

  expect(onDeleteAccount).toHaveBeenCalledTimes(1);
});
