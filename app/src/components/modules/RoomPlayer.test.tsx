import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { createContext, createRef } from 'react';

import { Refused } from '../../lib/api/refused';
import { RoomPlayer, type RoomPlayerHandle } from './RoomPlayer';

/**
 * Fetching the link, and what the screen says when that goes wrong.
 *
 * **The player is faked here on purpose, and the fake is small.** What it
 * stands in for is `expo-audio` — the platform players, whose streaming is a
 * question about a device, not a suite. What *is* worth asserting is
 * everything on this side of it: that a presigned link is never signed
 * before somebody asks for one, that a room whose audio has gone says so in
 * its own words, and that a room played to the end offers to play it again
 * from the top rather than from the end.
 */

interface Deck {
  player: {
    play: jest.Mock;
    pause: jest.Mock;
    seekTo: jest.Mock;
  };
  status: {
    isLoaded: boolean;
    playing: boolean;
    playbackState: string;
    currentTime: number;
    duration: number;
  };
}

/**
 * Every one of these is `mock`-prefixed because Jest requires it.
 *
 * `jest.mock`'s factory is hoisted above the imports, so a plain name
 * captured inside it is read before it exists — and rather than let that
 * fail at run time, Babel refuses the file outright unless the name says it
 * is a mock.
 */
const mockDeckContext = createContext<Deck | null>(null);

/** What the faked hooks hand the component, set per test. */
let mockDeck: Deck;
/** Every source a player was created against, in order. */
let mockSources: unknown[];
/** How many times the audio session was put into a playing shape. */
const mockForPlayingBack = jest.fn();

jest.mock('../../lib/replay/session', () => ({
  forPlayingBack: () => mockForPlayingBack(),
}));

jest.mock('expo-audio', () => {
  // `require`, because `jest.mock`'s factory is hoisted above this file's
  // imports — an `import` would not have been evaluated yet.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { useContext } = require('react');

  return {
    useAudioPlayer: (source: unknown) => {
      mockSources.push(source);
      return useContext(mockDeckContext).player;
    },
    useAudioPlayerStatus: () => useContext(mockDeckContext).status,
  };
});

function seated(over: Partial<Deck['status']> = {}): Deck {
  return {
    player: {
      play: jest.fn(),
      pause: jest.fn(),
      seekTo: jest.fn().mockResolvedValue(undefined),
    },
    status: {
      isLoaded: true,
      playing: true,
      playbackState: 'readyToPlay',
      currentTime: 0,
      duration: 600,
      ...over,
    },
  };
}

async function show(findIt: () => Promise<string>) {
  await render(
    <mockDeckContext.Provider value={mockDeck}>
      <RoomPlayer findIt={findIt} />
    </mockDeckContext.Provider>
  );
  return findIt;
}

/** Mounted with a handle, the way `rooms/[id]` holds one. */
async function shown(findIt: () => Promise<string>) {
  const handle = createRef<RoomPlayerHandle>();
  await render(
    <mockDeckContext.Provider value={mockDeck}>
      <RoomPlayer findIt={findIt} ref={handle} />
    </mockDeckContext.Provider>
  );
  return handle;
}

beforeEach(() => {
  mockDeck = seated();
  mockSources = [];
  mockForPlayingBack.mockClear();
});

/** Tap the one control that is drawn before anything is playing. */
async function askToHearIt() {
  await act(async () => {
    fireEvent.press(screen.getByRole('button', { name: 'Hear this room' }));
  });
}

it('signs nothing until somebody asks to hear it', async () => {
  // The link lives fifteen minutes. Signing on the way in would hand a dead
  // URL to anybody who read the transcript first — which is what this screen
  // is mostly for — and would spend a presign on every glance at a past room.
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.m4a');
  await show(findIt);

  expect(findIt).not.toHaveBeenCalled();
  expect(mockSources).toHaveLength(0);
});

it('mounts the room against the link it was just given', async () => {
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.m4a');
  await show(findIt);

  await askToHearIt();

  expect(findIt).toHaveBeenCalledTimes(1);
  expect(mockSources[0]).toEqual({ uri: 'https://store.test/room.m4a' });
});

it('starts playing the moment the room has loaded, without a second tap', async () => {
  // The tap already said "hear this room". A second tap to start what the
  // first one asked for is the control not working.
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.m4a');
  await show(findIt);

  await askToHearIt();

  expect(mockDeck.player.play).toHaveBeenCalled();
});

it('puts the audio session into a shape that makes sound before it asks for any', async () => {
  // The session is global and imperative, and every screen that has touched
  // it left it as it was: the room and the debrief both run it as a two-way
  // call, which keeps the microphone hot and plays quietly. Worse is the
  // untouched case — a cold launch straight into the Library never sets it
  // at all, and the platform default respects the ringer switch, so a room
  // played with the phone on silent makes no sound and gives no reason.
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.m4a');
  await show(findIt);

  await askToHearIt();

  expect(mockForPlayingBack).toHaveBeenCalled();
});

it('says a room whose audio is gone is gone, not that something broke', async () => {
  // Reachable without doing anything wrong: recording can be switched off,
  // the tier window can expire between the list and the tap, or the delete
  // control further down this same screen can have run a moment ago.
  const findIt = jest
    .fn()
    .mockRejectedValue(
      new Refused('recording_not_available', 'There is no saved audio for this room.', 404)
    );
  await show(findIt);

  await askToHearIt();

  expect(screen.getByText('There is no saved audio for this room.')).toBeTruthy();
  expect(mockSources).toHaveLength(0);
});

it('offers the tap again after a failure, because the next one signs a fresh link', async () => {
  const findIt = jest.fn().mockRejectedValue(new Error('the store fell over'));
  await show(findIt);

  await askToHearIt();

  expect(screen.getByText(/did not play/)).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Hear this room' })).toBeTruthy();
});

it('says only its own sentence when the stream itself fails', async () => {
  // `CLAUDE.md`: a provider failure must never name the vendor to the user.
  // The platform surfaces its failure through status, and whatever detail it
  // carries — on a bad day, a signed URL with our bucket host in it — never
  // reaches the screen. The link is dropped too, so the next tap signs a
  // fresh one rather than retrying a URL that may have expired mid-stream.
  mockDeck = seated({ playbackState: 'failed', isLoaded: false, playing: false });
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.m4a');
  await show(findIt);

  await askToHearIt();

  expect(screen.queryByText(/failed|cloudflare|r2|exoplayer|avplayer/i)).toBeNull();
  expect(screen.getByText(/did not play/)).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Hear this room' })).toBeTruthy();
});

it('takes a finished room back to the top rather than replaying its last second', async () => {
  // The playhead sits at the end when a room finishes, which is right — it
  // says you heard all of it. What is wrong is Play from there: it starts at
  // the end and appears to do nothing at all.
  //
  // Read off the position rather than remembered from an ended event. The
  // same thing is true of somebody who dragged the bar to the end and then
  // pressed Play, and an event would have covered one of the two.
  mockDeck = seated({ playing: false, currentTime: 600, duration: 600 });
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.m4a');
  await show(findIt);
  await askToHearIt();

  fireEvent.press(screen.getByRole('button', { name: 'Play' }));

  expect(mockDeck.player.seekTo).toHaveBeenCalledWith(0);
  expect(mockDeck.player.play).toHaveBeenCalled();
});

it('goes on from where it was paused, which is not the top', async () => {
  mockDeck = seated({ playing: false, currentTime: 240, duration: 600 });
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.m4a');
  await show(findIt);
  await askToHearIt();

  fireEvent.press(screen.getByRole('button', { name: 'Play' }));

  expect(mockDeck.player.seekTo).not.toHaveBeenCalled();
  expect(mockDeck.player.play).toHaveBeenCalled();
});

it('opens the room and lands on the moment somebody asked for', async () => {
  // #69's payoff. Tapping a timestamp in the transcript on a room that is
  // not playing has to do both halves — sign the link and seek — because the
  // alternative is a control that starts from the top and leaves somebody to
  // find the moment themselves, which is the offer that already existed.
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.m4a');
  const handle = await shown(findIt);

  await act(async () => {
    handle.current?.hearFrom(92);
  });

  expect(findIt).toHaveBeenCalledTimes(1);
  expect(mockDeck.player.seekTo).toHaveBeenCalledWith(92);
  expect(mockDeck.player.play).toHaveBeenCalled();
});

it('seeks again when the same moment is asked for twice', async () => {
  // Tapping one line twice is a real thing to do — you missed it the first
  // time. Two calls are two seeks, which is the plain reading of a command
  // and the reason this is a handle rather than a changing prop: a prop
  // holding the same number would be unchanged, and the control would look
  // broken exactly when somebody leaned on it.
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.m4a');
  const handle = await shown(findIt);

  await act(async () => {
    handle.current?.hearFrom(92);
  });
  mockDeck.player.seekTo.mockClear();
  await act(async () => {
    handle.current?.hearFrom(92);
  });

  expect(mockDeck.player.seekTo).toHaveBeenCalledWith(92);
});

it('signs nothing until somebody asks for a moment or presses play', async () => {
  // The guard that keeps the presign lazy. Merely holding a handle must not
  // spend a signature — that would put a request on every visit to a past
  // room, which is the thing this component exists to avoid.
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.m4a');
  await shown(findIt);

  expect(findIt).not.toHaveBeenCalled();
});
