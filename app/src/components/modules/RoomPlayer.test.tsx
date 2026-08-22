import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { createContext, type ReactNode } from 'react';

import { Refused } from '../../lib/api/refused';
import { RoomPlayer } from './RoomPlayer';

/**
 * Fetching the link, and what the screen says when that goes wrong.
 *
 * **The streaming element is faked here on purpose, and the fake is small.**
 * What it stands in for is a native decoder reached by a private path into
 * `react-native-audio-api` (#68) — the one thing in this feature no test can
 * meaningfully assert, because whether it decodes Ogg Opus over HTTP ranges is
 * a question about a device. What *is* worth asserting is everything on this
 * side of it: that a presigned link is never signed before somebody asks for
 * one, that a room whose audio has gone says so in its own words, and that a
 * room played to the end offers to play it again from the top rather than from
 * the end.
 */

interface Tag {
  play: jest.Mock;
  pause: jest.Mock;
  seekToTime: jest.Mock;
  ready: boolean;
  playbackState: 'idle' | 'playing' | 'paused';
  currentTime: number;
  duration: number;
}

/**
 * Every one of these is `mock`-prefixed because Jest requires it.
 *
 * `jest.mock`'s factory is hoisted above the imports, so a plain name captured
 * inside it is read before it exists — and rather than let that fail at run
 * time, Babel refuses the file outright unless the name says it is a mock.
 */
const mockTagContext = createContext<Tag | null>(null);

/** What the faked element hands its children, set per test. */
let mockTag: Tag;
/** The last `onError` the element was given, so a test can make it fail. */
let mockBreaks: (error: Error) => void;
/** Every source the element was mounted against, in order. */
let mockSources: unknown[];
/** How many times the audio session was put into a playing shape. */
const mockForPlayingBack = jest.fn();

jest.mock('../../lib/replay/session', () => ({
  forPlayingBack: () => mockForPlayingBack(),
}));

jest.mock('../../lib/replay/element', () => {
  // Required inside rather than imported above, for the hoisting reason the
  // names carry: the factory runs before this file's imports have been
  // evaluated.
  const { useContext } = require('react');
  const { View } = require('react-native');

  return {
    AudioElement: ({
      children,
      source,
      onError,
    }: {
      children: ReactNode;
      source: unknown;
      onError: (error: Error) => void;
    }) => {
      mockSources.push(source);
      mockBreaks = onError;
      return <View testID="element">{children}</View>;
    },
    useAudioTagContext: () => useContext(mockTagContext),
  };
});

function seated(over: Partial<Tag> = {}): Tag {
  return {
    play: jest.fn(),
    pause: jest.fn(),
    seekToTime: jest.fn(),
    ready: true,
    playbackState: 'playing',
    currentTime: 0,
    duration: 600,
    ...over,
  };
}

async function show(findIt: () => Promise<string>) {
  await render(
    <mockTagContext.Provider value={mockTag}>
      <RoomPlayer findIt={findIt} />
    </mockTagContext.Provider>
  );
  return findIt;
}

beforeEach(() => {
  mockTag = seated();
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
  // The link lives fifteen minutes. Signing on the way in would hand a dead URL
  // to anybody who read the transcript first — which is what this screen is
  // mostly for — and would spend a presign on every glance at a past room.
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.opus');
  await show(findIt);

  expect(findIt).not.toHaveBeenCalled();
  expect(screen.queryByTestId('element')).toBeNull();
});

it('mounts the room against the link it was just given', async () => {
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.opus');
  await show(findIt);

  await askToHearIt();

  expect(findIt).toHaveBeenCalledTimes(1);
  expect(mockSources[0]).toEqual({ uri: 'https://store.test/room.opus' });
});

it('puts the audio session into a shape that makes sound before it asks for any', async () => {
  // The session is global and imperative, and every screen that has touched it
  // left it as it was: the room and the debrief both set `playAndRecord`, which
  // keeps the microphone hot and plays quietly. Worse is the untouched case —
  // a cold launch straight into the Library never sets a category at all, and
  // the platform default respects the ringer switch, so a room played with the
  // phone on silent makes no sound and gives no reason.
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.opus');
  await show(findIt);

  await askToHearIt();

  expect(mockForPlayingBack).toHaveBeenCalled();
});

it('says a room whose audio is gone is gone, not that something broke', async () => {
  // Reachable without doing anything wrong: recording can be switched off, the
  // tier window can expire between the list and the tap, or the delete control
  // further down this same screen can have run a moment ago.
  const findIt = jest
    .fn()
    .mockRejectedValue(
      new Refused('recording_not_available', 'There is no saved audio for this room.', 404)
    );
  await show(findIt);

  await askToHearIt();

  expect(screen.getByText('There is no saved audio for this room.')).toBeTruthy();
  expect(screen.queryByTestId('element')).toBeNull();
});

it('offers the tap again after a failure, because the next one signs a fresh link', async () => {
  const findIt = jest.fn().mockRejectedValue(new Error('the store fell over'));
  await show(findIt);

  await askToHearIt();

  expect(screen.getByText(/did not play/)).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Hear this room' })).toBeTruthy();
});

it('does not name the vendor when the stream itself fails', async () => {
  // `CLAUDE.md`: a provider failure must never name the vendor to the user. The
  // element hands us its own `Error`, whose message is whatever ffmpeg or the
  // store said.
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.opus');
  await show(findIt);
  await askToHearIt();

  await act(async () => {
    mockBreaks(new Error('AVFoundation: cannot decode https://r2.cloudflarestorage.com/x'));
  });

  expect(screen.queryByText(/AVFoundation|cloudflare|r2/i)).toBeNull();
  expect(screen.getByText(/did not play/)).toBeTruthy();
});

it('takes a finished room back to the top rather than replaying its last second', async () => {
  // The playhead sits at the end when a room finishes, which is right — it says
  // you heard all of it. What is wrong is Play from there: it starts at the end
  // and appears to do nothing at all.
  //
  // Read off the position rather than remembered from an `ended` event. The
  // same thing is true of somebody who dragged the bar to the end and then
  // pressed Play, and an event would have covered one of the two.
  mockTag = seated({ playbackState: 'idle', currentTime: 600, duration: 600 });
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.opus');
  await show(findIt);
  await askToHearIt();

  fireEvent.press(screen.getByRole('button', { name: 'Play' }));

  expect(mockTag.seekToTime).toHaveBeenCalledWith(0);
  expect(mockTag.play).toHaveBeenCalled();
});

it('goes on from where it was paused, which is not the top', async () => {
  mockTag = seated({ playbackState: 'paused', currentTime: 240, duration: 600 });
  const findIt = jest.fn().mockResolvedValue('https://store.test/room.opus');
  await show(findIt);
  await askToHearIt();

  fireEvent.press(screen.getByRole('button', { name: 'Play' }));

  expect(mockTag.seekToTime).not.toHaveBeenCalled();
  expect(mockTag.play).toHaveBeenCalled();
});
