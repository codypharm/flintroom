import { AccessibilityInfo } from 'react-native';
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
      attending={{ state: 'listening', since: Date.now() }}
      loudness={0}
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

describe('what the room says it is doing', () => {
  /**
   * #24. Five things look like silence to somebody in a room that has gone
   * quiet, and after a day of testing the architect reported two of them as
   * the panel being broken: it was thinking, and it had not heard them.
   */
  it('says nothing at all while it is simply listening', async () => {
    // The sound bar directly above already moves when they speak. Words here
    // would be a second answer to a question already answered, which is the
    // mistake that took a panelist off the screen mid-sentence.
    await show({ attending: { state: 'listening', since: Date.now() } });

    expect(screen.queryByText(/Got that/)).toBeNull();
    expect(screen.queryByText(/Working on it/)).toBeNull();
  });

  it('says it has you while the floor is still yours', async () => {
    // The opening floor (#79) may hold for ninety seconds across several
    // finals. Without this it is indistinguishable from the room failing to
    // answer — the fix for one reading as the other.
    await show({ attending: { state: 'heard', since: Date.now() } });

    expect(await screen.findByText('Got that.')).toBeTruthy();
  });

  it('says it is working once it owes an answer', async () => {
    await show({ attending: { state: 'working', since: Date.now() } });

    expect(await screen.findByText('Working on it.')).toBeTruthy();
  });

  it('says nothing while a panelist has the floor', async () => {
    // The caption and the developing tray already say who is talking. This
    // describes what happens while the floor is the presenter's and must stay
    // out of the way otherwise.
    await show({
      floor: 'panel',
      attending: { state: 'working', since: Date.now() },
    });

    expect(screen.queryByText(/Working on it/)).toBeNull();
  });

  it('says when nothing has reached the room at all', async () => {
    // #77. The server split "it did not hear them" in two, because the two
    // halves want different things: a final that never arrived wants the
    // sentence again, and a microphone that has never delivered anything wants
    // the phone checked. `listening` was quietly claiming both, so a presenter
    // with a dead microphone got the same blank screen as one being thought
    // about — worse on a phone lying flat where nobody is watching it.
    await show({ attending: { state: 'unheard', since: Date.now() } });

    expect(await screen.findByText(/check your microphone/)).toBeTruthy();
  });

  it('does not tell somebody their microphone is broken once it has heard them', async () => {
    // The whole safety argument. `docs/echo-cancellation.md` measured a quiet
    // room on this app's shipped audio configuration reading exact digital
    // zero, so an ordinary pause and an unplugged microphone look identical
    // from here. Only the server may say this, and only about a room that has
    // never heard anything — which is why the state is not derived on device.
    await show({ attending: { state: 'listening', since: Date.now() } });

    expect(screen.queryByText(/check your microphone/)).toBeNull();
  });

  it('yields to the warning that something is actually wrong', async () => {
    // Two lines of machinery on a hands-free screen is a paragraph nobody
    // glancing will read, and "we can barely hear you" is the more actionable.
    await show({
      hearing: 'faint',
      attending: { state: 'working', since: Date.now() },
    });

    expect(await screen.findByText(/barely hear you/)).toBeTruthy();
    expect(screen.queryByText(/Working on it/)).toBeNull();
  });
});

describe('the room moving while it works', () => {
  /**
   * The bars are dead at exactly the wrong moment: the floor is still the
   * presenter's, they have stopped talking, and the room owes them an answer.
   * Nothing on screen moves, which is when they start to wonder whether it
   * heard them at all.
   *
   * The animation itself is verified on a device — what is worth holding here
   * is that the state reaches the bars and that it is bounded to the one case
   * where the row is otherwise still.
   */
  it('does not move for somebody who asked us not to move things', async () => {
    // The real obligation here, and the only part of an animation worth
    // asserting off a device. `useReduceMotion`'s rule is to honour it by
    // CUTTING rather than slowing — a shortened swell is still a swell, and the
    // setting means "do not move things", not "move them less".
    //
    // The words stay either way, which is what makes cutting safe: somebody who
    // has turned motion off is not left with less information than everyone
    // else, only with less movement.
    jest
      .spyOn(AccessibilityInfo, 'isReduceMotionEnabled')
      .mockResolvedValue(true);

    await show({ attending: { state: 'working', since: Date.now() } });

    expect(await screen.findByText('Working on it.')).toBeTruthy();
  });

  it('leaves the bars to the presenter while they are still talking', async () => {
    // `heard` gets no motion of its own. They are mid-sentence, so the bars are
    // already alive with their own voice, and a second animation would be
    // fighting them for the same pixels.
    await show({
      attending: { state: 'heard', since: Date.now() },
      loudness: 0.6,
    });

    expect(await screen.findByText('Got that.')).toBeTruthy();
  });

  it('does not move while a panelist has the floor', async () => {
    // The tray's developing print and its amber ring already carry that. Two
    // things saying "somebody is speaking" is the bug that took a panelist off
    // the screen mid-sentence.
    await show({
      floor: 'panel',
      attending: { state: 'working', since: Date.now() },
    });

    expect(screen.queryByText(/Working on it/)).toBeNull();
  });
});
