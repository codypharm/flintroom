import { fireEvent, render, screen, userEvent } from '@testing-library/react-native';

import { SettingsScreen, type Holdings, type Recording } from './SettingsScreen';

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
  minutesRemaining: 15,
};

/**
 * The recording preference, which arrives from its own request and so is its
 * own prop since #92 — a failed `/v1/materials` must not take a control with it.
 */
const SAVING: Recording = { recordsRooms: true, retentionDays: 30 };

async function show(
  holdings: Partial<Holdings> = {},
  props = {},
  recording: Recording | null = SAVING,
) {
  await render(
    <SettingsScreen
      holdings={{ ...NOTHING, ...holdings }}
      recording={recording}
      onRecordingChange={jest.fn()}
      onDeleteAccount={jest.fn()}
      onSignOut={jest.fn()}
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
  await show({}, {}, { ...SAVING, recordsRooms: false });

  expect(screen.getByText(/not being saved/i)).toBeOnTheScreen();
});

it('still lists rooms already held when recording is off', async () => {
  /**
   * Turning it off stops future rooms; it does not delete past ones, because
   * they were made under a disclosure the person accepted. Hiding them here
   * would imply otherwise.
   */
  await show({ rooms: 3 }, {}, { ...SAVING, recordsRooms: false });

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

it('offers a way out of the account that is not a way to destroy it', async () => {
  // There was no sign-out control at all until 2026-08-20, which is why a
  // signed-out state was unreachable except by a token expiring on its own —
  // and why #86 could sit undiscovered.
  //
  // Drawn as an ordinary control rather than a destructive one, because it
  // destroys nothing: the rooms, the transcripts and the minutes are all still
  // there next time. Two red buttons side by side is how somebody taps the
  // wrong one.
  const onSignOut = jest.fn();
  await show({}, { onSignOut });

  await userEvent.press(screen.getByLabelText('Sign out'));

  expect(onSignOut).toHaveBeenCalled();
});

describe('before the account has been read, and when it cannot be', () => {
  /**
   * This screen fetched nothing until #85 — every figure on it was a literal,
   * so there was no such thing as not knowing yet. Now there is, and the rule
   * is the same one the rest of the screen follows: state facts, and when there
   * is no fact, say that rather than draw a zero.
   */

  async function unread(props = {}) {
    await render(
      <SettingsScreen
        holdings={null}
        // Null by default, because this block is about a screen that has no
        // answers yet or could not get them — and the preference is one of the
        // answers. A test that wants it known passes it through `props`.
        recording={null}
        onRecordingChange={jest.fn()}
        onDeleteAccount={jest.fn()}
        onSignOut={jest.fn()}
        {...props}
      />
    );
  }

  it('states no figure it does not have', async () => {
    await unread({ reading: true });

    // The dangerous shape is a zero, because a zero is a claim. "No rooms
    // saved" while the request is still in flight tells somebody we hold
    // nothing of theirs, which is the reassuring direction to be wrong in.
    expect(screen.queryByText(/no rooms saved/i)).not.toBeOnTheScreen();
    expect(screen.queryByText(/minutes/i)).not.toBeOnTheScreen();
  });

  it('never draws the recording switch in a position it cannot vouch for', async () => {
    /**
     * A switch has no third position. Drawn while the answer is unknown it
     * states one — and off would say recordings are not being saved when the
     * next room may well be. So there is no switch until there is an answer.
     */
    await unread({ reading: true });

    expect(screen.queryByRole('switch')).not.toBeOnTheScreen();
  });

  it('says the read failed rather than showing an empty account', async () => {
    await unread({ reading: false });

    expect(screen.getByText(/could not/i)).toBeOnTheScreen();
  });

  it('offers another go when one was handed to it', async () => {
    const onRetry = jest.fn();
    await unread({ reading: false, onRetry });

    await userEvent.press(screen.getByText(/try again/i));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('lets somebody leave or delete an account it could not read', async () => {
    /**
     * The one thing this screen must never do. Sign-out and deletion need a
     * credential, not an inventory — and an account whose reads are failing is
     * exactly the account somebody wants to get out of. Putting both behind a
     * successful fetch traps them, and deletion is an App Store requirement.
     */
    const onSignOut = jest.fn();
    const onDeleteAccount = jest.fn();
    await unread({ reading: false, onSignOut, onDeleteAccount });

    await userEvent.press(screen.getByLabelText('Sign out'));
    await userEvent.press(screen.getByText(/delete account/i));

    expect(onSignOut).toHaveBeenCalledTimes(1);
    expect(onDeleteAccount).toHaveBeenCalledTimes(1);
  });
});

it('does not write a zero over a balance it has not read', async () => {
  /**
   * The balance arrives separately from the inventory — the app bar owns that
   * read for all four tabs and swallows its own failures — so this row can be
   * unknown while everything beside it is fine. A `0` written into that gap
   * tells somebody they have run out of minutes, which is both a claim about
   * their money and the one that stops them starting a room.
   */
  await show({ minutesRemaining: null });

  expect(screen.queryByText(/0 minutes/i)).not.toBeOnTheScreen();
  expect(screen.getByText(/could not read this/i)).toBeOnTheScreen();
});

it('will not move the switch until the server has agreed', async () => {
  /**
   * The surface brief names this the worst failure the screen has: "a toggle
   * that appears to have flipped and did not". An optimistic flip is exactly
   * that shape for as long as the request is in flight, and on a phone that is
   * not a short window.
   *
   * So the switch stays where it is and disables while the write is out. The
   * greyed control is the feedback; the position stays a fact about the
   * account rather than a guess about it.
   */
  await show({}, { writing: true }, { ...SAVING, recordsRooms: true });

  const control = screen.getByRole('switch');

  expect(control.props.value).toBe(true);
  expect(control.props.disabled).toBe(true);
});

it('opens what is attached rather than only counting it', async () => {
  /**
   * `docs/privacy-policy.md` states that attached material can be deleted in
   * Settings. The row counted it and stopped there, so the policy described a
   * control that existed nowhere in the app.
   *
   * The list is a pushed screen rather than rows here: the surface brief says
   * this screen fails the moment it reads as a dashboard, and a deck-by-deck
   * list with a destructive control on each row is one.
   */
  const onOpenMaterial = jest.fn();
  await show({ materials: 2 }, { onOpenMaterial });

  await userEvent.press(screen.getByLabelText('Attached material'));

  expect(onOpenMaterial).toHaveBeenCalledTimes(1);
});

it('offers the way in even with nothing attached', async () => {
  // An empty inventory is still an inventory, and somebody checking what is
  // held should be able to see for themselves rather than trust the count.
  const onOpenMaterial = jest.fn();
  await show({ materials: 0 }, { onOpenMaterial });

  await userEvent.press(screen.getByLabelText('Attached material'));

  expect(onOpenMaterial).toHaveBeenCalledTimes(1);
});

/**
 * #92 — one read failing must not take the others down with it.
 *
 * The route gathered three independent calls with `Promise.all`, so a 502 on
 * `/v1/materials` discarded a `/v1/preferences/recording` that had answered 200.
 */
describe('when one read failed and another did not', () => {
  it('still offers the switch that turns recording off', async () => {
    // `docs/privacy-policy.md` promises it in as many words — "Stop rooms being
    // recorded. A switch in Settings." A control the privacy policy names must
    // not disappear because an unrelated request timed out, and its own answer
    // is sitting in memory.
    await render(
      <SettingsScreen
        holdings={null}
        recording={{ recordsRooms: true, retentionDays: 365 }}
        onRecordingChange={jest.fn()}
        onDeleteAccount={jest.fn()}
        onSignOut={jest.fn()}
      />,
    );

    expect(screen.getByRole('switch')).toBeOnTheScreen();
  });

  it('says the counts are unknown rather than dropping them quietly', async () => {
    // The all-or-nothing this replaces was deliberate: "a screen that rendered
    // three of four rows and quietly dropped the fourth would be understating
    // what we hold, in the one place that must not." The load-bearing word is
    // *quietly* — a section that says it could not read understates nothing.
    await render(
      <SettingsScreen
        holdings={null}
        recording={{ recordsRooms: true, retentionDays: 365 }}
        onRecordingChange={jest.fn()}
        onDeleteAccount={jest.fn()}
        onSignOut={jest.fn()}
      />,
    );

    expect(screen.getByText(/could not read/i)).toBeOnTheScreen();
  });

  it('shows no switch when the preference itself is what failed', async () => {
    // A switch drawn from nothing would have to pick a position, and either
    // position is a claim about whether rooms are being recorded. Absent is the
    // only honest state.
    await render(
      <SettingsScreen
        holdings={null}
        recording={null}
        onRecordingChange={jest.fn()}
        onDeleteAccount={jest.fn()}
        onSignOut={jest.fn()}
      />,
    );

    expect(screen.queryByRole('switch')).toBeNull();
  });
});
