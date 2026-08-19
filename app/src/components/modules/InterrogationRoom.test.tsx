import { fireEvent, render, screen } from '@testing-library/react-native';

import { InterrogationRoom } from './InterrogationRoom';

/**
 * The room, as a surface with no opinions about sockets.
 *
 * Everything here is a prop, because the screen above owns the microphone, the
 * connection and the meter, and none of those can be rendered. What is left is
 * the part a person actually experiences under pressure: who is on me, what did
 * they just ask, is it my turn, and how do I stop.
 */

async function show(over: Partial<Parameters<typeof InterrogationRoom>[0]> = {}) {
  const onEnd = jest.fn();

  await render(
    <InterrogationRoom
      panel={PANEL}
      speaking={null}
      line={null}
      floor="yours"
      hearing="silent"
      phase="live"
      elapsed={null}
      onEnd={onEnd}
      {...over}
    />
  );

  return { onEnd };
}

const PANEL = [
  { name: 'cfo', title: 'The CFO' },
  { name: 'champion', title: 'The Champion' },
  { name: 'technical_skeptic', title: 'The Technical Skeptic' },
];

it('seats one archetype per chair the panel was assembled with', async () => {
  // The far field is the room. Three seats means three people on the other
  // side of the table, and a screen that drew a fixed number would be showing
  // somebody a panel they did not assemble.
  await show({ panel: PANEL.slice(0, 2) });

  expect(
    screen.queryAllByTestId('tray', { includeHiddenElements: true })
  ).toHaveLength(2);
});

it('names who is asking, beside what they asked', async () => {
  // Caption standards want the speaker identified wherever more than one
  // person speaks, and a tray deepening in peripheral vision tells a deaf
  // reader nothing about which archetype is on them. The tray is
  // reinforcement; this is the answer.
  await show({ line: { speaker: 'cfo', text: 'Where does that 40% come from?' } });

  expect(screen.getByText('The CFO')).toBeTruthy();
  expect(screen.getByText('Where does that 40% come from?')).toBeTruthy();
});

it('still shows a line from an archetype it has no title for', async () => {
  // The catalogue is fetched and the room is not. A seat the client cannot
  // name is a caption it must still render — dropping the line would silence
  // the panel for the person who most needs it, over a missing label.
  await show({ line: { speaker: 'internal_blocker', text: 'And the timeline?' } });

  expect(screen.getByText('And the timeline?')).toBeTruthy();
});

it('says the floor is yours before anybody has spoken', async () => {
  // The panel does not open the room — a turn is only composed once somebody
  // has said something — and the meter starts when the channel does. Silence
  // with no explanation is a minute of somebody's allowance spent wondering
  // whether the app is broken.
  await show({ line: null, phase: 'live' });

  expect(screen.getByText('The room is listening. Take it away.')).toBeTruthy();
});

it('does not end the room on one tap', async () => {
  // The phone is flat on a desk under somebody's hands while they gesture, and
  // the control is at the near edge. A brushed thumb would otherwise end a
  // rehearsal that cannot be resumed.
  const { onEnd } = await show();

  fireEvent.press(screen.getByLabelText('End the room'));

  expect(onEnd).not.toHaveBeenCalled();
  expect(await screen.findByText('Tap again to end')).toBeTruthy();
});

it('ends the room on the second tap', async () => {
  const { onEnd } = await show();

  fireEvent.press(screen.getByLabelText('End the room'));
  fireEvent.press(await screen.findByLabelText('Tap again to end the room'));

  expect(onEnd).toHaveBeenCalledTimes(1);
});

it('offers exactly one control, and no way to speak on demand', async () => {
  // Hands-free by design: the microphone is open for the length of the room
  // and interrupting is done by talking over somebody. A push-to-talk target
  // would remove the one feature the voice provider was chosen for, and any
  // second control is something to hunt for on a screen nobody is looking at.
  await show({ line: { speaker: 'cfo', text: 'And the margin?' }, floor: 'panel' });

  expect(screen.queryAllByRole('button')).toHaveLength(1);
});

it('keeps the last question on screen while the room closes', async () => {
  // The beat before the debrief holds the thing you are still chewing on,
  // rather than an empty screen. And End is gone: the room is already over,
  // and a control that no longer does anything is a control that lies.
  await show({
    phase: 'ending',
    line: { speaker: 'cfo', text: 'You never answered the first one.' },
  });

  expect(screen.getByText('You never answered the first one.')).toBeTruthy();
  expect(screen.queryAllByRole('button')).toHaveLength(0);
});

it('says so when the room can barely hear you, and only then', async () => {
  // The one thing a presence light cannot carry: it reads "hearing you" while
  // the transcriber gets mush, the room answers a garbled question, and the
  // panel looks stupid for it.
  await show({ floor: 'yours', hearing: 'faint' });
  expect(screen.getByText(/barely hear you/)).toBeTruthy();

  await show({ floor: 'panel', hearing: 'faint' });
  expect(screen.queryByText(/barely hear you/)).toBeNull();
});

it('draws the room across, one seat per archetype, whoever is speaking', async () => {
  // Stacked, three seats were a list of three things; across, they are people
  // on the other side of a table — which is what the product is a rehearsal
  // for. Nobody is ever removed between turns: a panelist who vanished when
  // somebody else spoke would be a table that keeps changing size.
  await show({ panel: PANEL, speaking: 'champion' });

  expect(
    screen.queryAllByTestId('tray', { includeHiddenElements: true })
  ).toHaveLength(3);
});

it('keeps every seat drawn while one of them holds the floor', async () => {
  const quiet = await show({ panel: PANEL, speaking: null });
  const quietSeats = screen.queryAllByTestId('tray', { includeHiddenElements: true }).length;

  await show({ panel: PANEL, speaking: 'cfo' });
  const loudSeats = screen.queryAllByTestId('tray', { includeHiddenElements: true }).length;

  expect(loudSeats).toBe(quietSeats);
  expect(quiet.onEnd).not.toHaveBeenCalled();
});

it('counts up rather than down', async () => {
  // §4.6 bans a DEPLETING counter, because a number falling toward zero makes
  // people ration and rationing users churn. Elapsed time is the opposite
  // framing of the same fact, and it is what a rehearsal needs: the slot you
  // are practising for has a length, and the useful question is how far into
  // it you are.
  await show({ elapsed: 272 });

  expect(screen.getByText('4:32')).toBeTruthy();
});

it('reads the clock to a screen reader as words, not as a colon', async () => {
  // "4:32" read aloud is a guess — a time of day, "four thirty-two", or "four
  // colon three two", depending on the reader. Somebody relying on it during a
  // room is the last person who should have to work out which.
  await show({ elapsed: 272 });

  expect(screen.getByLabelText('4 minutes 32 seconds in the room')).toBeTruthy();
});

it('shows no clock before the room is open', async () => {
  // Nothing has elapsed yet, and a 0:00 sitting over a screen that is still
  // connecting is a clock measuring the wrong thing.
  await show({ elapsed: null, phase: 'opening' });

  expect(screen.queryByText(/^\d+:\d\d$/)).toBeNull();
});
