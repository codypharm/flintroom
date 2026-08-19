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

  await render(<RoomRead {...props} />);
  return props;
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

it('offers the way to what the room found', async () => {
  // The transcript is the record; the debrief is the work. Somebody who has
  // just re-read a bad answer wants the finding, not a back gesture.
  const { onDebrief } = await setup();

  await userEvent.press(screen.getByLabelText('What the room found'));

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
