import { render, screen, userEvent } from '@testing-library/react-native';
import { Text } from 'react-native';

import { RoomRead, type RoomReadProps } from './RoomRead';

/**
 * One room, read back.
 *
 * The Library's other half — "view the detail of discussion". What makes this
 * hard is not fetching the lines, it is refusing the two shapes it would fall
 * into on its own: a chat, and a report.
 */

const LINES = [
  { ordinal: 0, speaker: 'user', text: 'We grew forty percent last quarter.', saidAt: '2026-08-20T09:12:04Z', beganAtSeconds: 0 },
  { ordinal: 1, speaker: 'cfo', text: 'Off what base, and at what cost?', saidAt: '2026-08-20T09:12:19Z', beganAtSeconds: 15.2 },
  { ordinal: 2, speaker: 'user', text: 'We are really pleased with the trajectory.', saidAt: '2026-08-20T09:12:41Z', beganAtSeconds: 37.9 },
];

async function setup(overrides: Partial<RoomReadProps> = {}) {
  const props: RoomReadProps = {
    when: 'Today',
    who: 'The CFO and The Technical Skeptic',
    lines: LINES,
    onDebrief: jest.fn(),
    ...overrides,
  };

  // The render result too, so a test can ask what order things came out in.
  const drawn = await render(<RoomRead {...props} />);
  return { ...props, ...drawn };
}

it('puts the player above the room it plays, and below the way to work on it', async () => {
  // A slot rather than a component this file imports, and the reason is not
  // taste: what streams a room is `expo-audio` (#68, re-homed by #25), and
  // that module cannot even be *imported*
  // under Jest — its native binding throws at load. Any
  // screen that pulled it in transitively would need it mocked in every test it
  // has, over a control none of them are about.
  //
  // Placement is the design. Under the coach, because going through a room is
  // what this screen is for and hearing it again is not; above the transcript,
  // because on a forty-turn room anything below the lines is out of reach.
  await setup({ player: <Text>a player</Text> });

  const drawn = JSON.stringify(screen.toJSON());
  expect(drawn.indexOf('"Go through it with the coach"')).toBeLessThan(
    drawn.indexOf('"a player"')
  );
  expect(drawn.indexOf('"a player"')).toBeLessThan(
    drawn.indexOf('"We grew forty percent last quarter."')
  );
});

it('draws no player where there is nothing to play', async () => {
  // A room that was never recorded, or whose window has passed. The route
  // decides; this only refuses to leave a gap where a control would be.
  await setup({ player: null });

  expect(screen.queryByText('a player')).toBeNull();
});

it('reads back as a script, with every line attributed', async () => {
  await setup();

  expect(screen.getByText('Off what base, and at what cost?')).toBeTruthy();
  expect(screen.getByText('The CFO')).toBeTruthy();
});

it('calls the presenter by name rather than by the wire’s word for them', async () => {
  // `user` is storage. Nobody reading their own rehearsal should be labelled
  // with the string the database uses for them.
  await setup();

  expect(screen.queryByText('user')).toBeNull();
  expect(screen.getAllByText('You').length).toBeGreaterThan(0);
});

it('says where in the room each line fell', async () => {
  // Offsets from the start rather than clock times: "nine twelve" places a line
  // in a day, and what a reader wants is where it fell in the twelve minutes.
  await setup();

  expect(screen.getByText('0:15')).toBeTruthy();
});

it('draws no back control of its own, because the stack draws a real one', async () => {
  // This screen grew a hand-rolled chevron because the layout hid every stack
  // header, and the layout hid them because a route with no `Stack.Screen`
  // entry falls back to its filename. That was an argument for configuring
  // titles, not for switching off a native subsystem — and the drawn one had a
  // defect the native one cannot have: it sat *inside* the ScrollView, so on a
  // long transcript the only way back scrolled off the top of the screen and
  // left nothing but the invisible edge-swipe.
  //
  // `rooms/[id]` turns the header on with an empty title, so the bar carries
  // the back button and this content keeps its own. The destination name moves
  // to `headerBackTitle`, which is where iOS puts it.
  await setup({});

  expect(screen.queryByLabelText(/^Back to/)).toBeNull();
});

it('offers the way to the coach', async () => {
  // The transcript is the record; the debrief is the work. Somebody who has
  // just re-read a bad answer wants the finding, not a back gesture.
  const { onDebrief } = await setup();

  await userEvent.press(screen.getByLabelText('Go through it with the coach'));

  expect(onDebrief).toHaveBeenCalled();
});

it('says what the coach door leads to, not just its name', async () => {
  // Field-tested 2026-08-27, same finding as the debrief's prep-sheet line:
  // a bare orange label read as dummy text. The door to the debrief is the
  // primary thing to do with a finished room, so it is drawn as the same
  // destination card the debrief uses — a supporting line and the disclosure
  // chevron.
  await setup();

  expect(
    screen.getByText('Your weakest answers, and the sparring to rebuild them.'),
  ).toBeOnTheScreen();
});

it('says plainly when a room has nothing in it', async () => {
  // The commonest room in the dev database: settled before the panel asked
  // anything. An empty script with a title over it reads as a failure to load.
  await setup({ lines: [] });

  expect(screen.getByText('Nothing was said in this room')).toBeTruthy();
});

it('puts no grade, mark, or verdict on a room', async () => {
  await setup();

  expect(screen.queryByText(/^[A-F][+-]?$/)).toBeNull();
  expect(screen.queryByText(/score/i)).toBeNull();
});

it('offers the coach before the transcript, not after all of it', async () => {
  // Reported from a phone. The control sat below every line, so on a
  // forty-turn room you scrolled the whole thing to reach the one thing this
  // screen is for. Somebody opening a past room either wants to re-read it or
  // to work on it, and only the second is worth a tap.
  //
  // Asserted on order rather than on a style, because "above the transcript"
  // is the property — a margin would not hold it.
  const drawn = await setup({});
  const shown = JSON.stringify(drawn.toJSON());
  const control = shown.indexOf('Go through it with the coach');
  const firstLine = shown.indexOf('Off what base');

  // Both found first. `indexOf` answers -1 for missing text, which is trivially
  // less than anything — this assertion passed while the control did not exist
  // at all, which is the whole failure mode of comparing positions.
  expect(control).toBeGreaterThan(-1);
  expect(firstLine).toBeGreaterThan(-1);
  expect(control).toBeLessThan(firstLine);
});

it('says what the tap does rather than naming where it lands', async () => {
  // "What the room found" is a noun phrase for a destination. It does not say
  // that somebody is waiting to talk it through — which, now that the coach
  // has a voice, is the whole of what happens next.
  await setup({});

  expect(screen.getByLabelText('Go through it with the coach')).toBeTruthy();
  expect(screen.queryByText('What the room found')).toBeNull();
});

describe('destroying this room’s audio', () => {
  /**
   * `docs/privacy-policy.md` promises this control and it existed nowhere.
   * Here rather than on the Library row, and that placement is the design:
   * deleting a *recording* is not deleting the *room* — the endpoint
   * deliberately leaves the transcript — so a "Delete" on a row that stays put
   * afterwards reads as a control that failed. On this screen the transcript
   * that survives is on the same page as the button.
   */

  const HELD = {
    held: true,
    deleting: false,
    deleted: false,
    refusal: null,
    onDelete: jest.fn(),
  };

  it('offers nothing when there is no audio to destroy', async () => {
    // Expired or never recorded. A control for something that is not there is
    // a promise the tap cannot keep.
    await setup({ recording: { ...HELD, held: false } });

    expect(screen.queryByLabelText('Delete the recording')).not.toBeOnTheScreen();
  });

  it('offers nothing when it does not know what the room holds', async () => {
    // The room row was not found — a deep link, or one deleted since. Not
    // knowing is not the same as nothing, and drawing the control either way
    // would be guessing.
    await setup({ recording: null });

    expect(screen.queryByLabelText('Delete the recording')).not.toBeOnTheScreen();
  });

  it('asks first, and says what survives', async () => {
    const onDelete = jest.fn();
    await setup({ recording: { ...HELD, onDelete } });

    await userEvent.press(screen.getByLabelText('Delete the recording'));

    expect(screen.getByText(/what was said stays/i)).toBeOnTheScreen();
    expect(onDelete).not.toHaveBeenCalled();
  });

  it('destroys it only on the second, explicit tap', async () => {
    const onDelete = jest.fn();
    await setup({ recording: { ...HELD, onDelete } });

    await userEvent.press(screen.getByLabelText('Delete the recording'));
    await userEvent.press(screen.getByLabelText('Yes, delete it'));

    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it('lets somebody back out', async () => {
    const onDelete = jest.fn();
    await setup({ recording: { ...HELD, onDelete } });

    await userEvent.press(screen.getByLabelText('Delete the recording'));
    await userEvent.press(screen.getByLabelText('Keep it'));

    expect(screen.queryByText(/what was said stays/i)).not.toBeOnTheScreen();
    expect(onDelete).not.toHaveBeenCalled();
  });

  it('says so once it is gone, rather than letting the control just vanish', async () => {
    /**
     * A destructive control that disappears on success has told somebody
     * nothing — and this one destroys something they cannot check, because
     * playback does not exist yet (#68). The sentence is the only receipt.
     */
    await setup({ recording: { ...HELD, held: false, deleted: true } });

    expect(screen.getByText(/recording is gone/i)).toBeOnTheScreen();
    expect(screen.getByText(/what was said is still here/i)).toBeOnTheScreen();
  });

  it('does not let a second tap through while the first is still out', async () => {
    await setup({ recording: { ...HELD, deleting: true } });

    expect(
      screen.getByLabelText('Delete the recording').props.accessibilityState
    ).toMatchObject({ disabled: true });
  });

  it('carries a refusal rather than swallowing it', async () => {
    await setup({
      recording: { ...HELD, refusal: 'That did not delete. Try again in a moment.' },
    });

    expect(screen.getByText(/did not delete/i)).toBeOnTheScreen();
  });
});


describe('hearing the moment a line happened', () => {
  /**
   * #69 wrote the offset, published it and carried it into the client type,
   * and until this nothing read it. The ticket's own case for the column was
   * that *"a fifteen-minute file starting at zero mostly is not"* worth
   * playing — so a transcript that cannot seek leaves the column half-built.
   */
  it('offers to hear the moment a line was said', async () => {
    const onSeek = jest.fn();
    await setup({ onSeek });

    await userEvent.press(screen.getByLabelText('Hear this from 0:15'));

    expect(onSeek).toHaveBeenCalledWith(15.2);
  });

  it('draws no such control for a room that was never timed', async () => {
    // Every room recorded before #69 has no offset, and a control that cannot
    // work is worse than one that is absent — the rule `DeckAttach` and
    // `AuthorRow` already follow, and `TablePlan` states from the other side:
    // an affordance on a statement is a lie about what a tap does.
    const onSeek = jest.fn();
    await setup({
      onSeek,
      lines: LINES.map((line) => ({ ...line, beganAtSeconds: null })),
    });

    expect(screen.queryByLabelText(/^Hear this from/)).toBeNull();
  });

  it('draws no such control where there is nothing to play', async () => {
    // A room whose recording was never made, has expired, or was deleted a
    // moment ago. The route passes no `onSeek` in exactly the cases it passes
    // no player, so the two cannot disagree about whether audio exists.
    await setup({});

    expect(screen.queryByLabelText(/^Hear this from/)).toBeNull();
  });

  it('labels a line with where it actually falls in the recording', async () => {
    // The offset used to be derived from `saidAt` relative to the first line —
    // approximate by construction, and measured from the first line rather than
    // the session start to avoid counting provisioning seconds nobody spoke in.
    //
    // The true offset does not carry that flaw: the mixer only advances once
    // audio is flowing, so provisioning is already excluded. So it takes over
    // the label as well as the seek, and the number somebody taps is the number
    // the audio jumps to.
    await setup({ onSeek: jest.fn() });

    expect(screen.getByText('0:15')).toBeTruthy();
  });
});

it('announces the date as the header it is', async () => {
  // The stack bar's title is deliberately empty — the date IS this screen's
  // title — so the rotor has to be able to land on it, as it can on every
  // other screen's heading.
  await setup();

  expect(screen.getByRole('header', { name: 'Today' })).toBeTruthy();
});
