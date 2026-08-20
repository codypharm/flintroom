import { render, screen, userEvent } from '@testing-library/react-native';

import { RoomRead, type RoomReadProps } from './RoomRead';

/**
 * One room, read back.
 *
 * The Library's other half — "view the detail of discussion". What makes this
 * hard is not fetching the lines, it is refusing the two shapes it would fall
 * into on its own: a chat, and a report.
 */

const LINES = [
  { ordinal: 0, speaker: 'user', text: 'We grew forty percent last quarter.', saidAt: '2026-08-20T09:12:04Z' },
  { ordinal: 1, speaker: 'cfo', text: 'Off what base, and at what cost?', saidAt: '2026-08-20T09:12:19Z' },
  { ordinal: 2, speaker: 'user', text: 'We are really pleased with the trajectory.', saidAt: '2026-08-20T09:12:41Z' },
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
