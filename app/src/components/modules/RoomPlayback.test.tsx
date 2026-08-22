import { act, fireEvent, render, screen } from '@testing-library/react-native';

import { RoomPlayback, type RoomPlaybackProps } from './RoomPlayback';

/**
 * The transport for a room somebody wants to hear again.
 *
 * Presentation only, and that is the point of the split: the element that
 * actually streams the audio is a private path into a library (#68), and
 * nothing about what this says or offers should be reachable only by mounting
 * a native decoder.
 */

async function show(overrides: Partial<RoomPlaybackProps> = {}) {
  const props: RoomPlaybackProps = {
    state: 'idle',
    at: 0,
    runs: 0,
    refusal: null,
    onPlay: jest.fn(),
    onPause: jest.fn(),
    onSeek: jest.fn(),
    ...overrides,
  };

  await render(<RoomPlayback {...props} />);
  return props;
}

/**
 * The bar reports its own width, before a tap on it can mean anything.
 *
 * Wrapped and awaited. A bare `fireEvent` for a synthetic `layout` here leaves
 * React's act scope open across the end of the test, and React 19 then discards
 * the *next* test's tree — which fails as "unable to find an element" against a
 * component that is perfectly fine, three tests further down. `jest.config.js`
 * describes the same trap for an unawaited `render`.
 */
async function measure(width = 300) {
  await act(async () => {
    fireEvent(screen.getByTestId('scrub'), 'layout', {
      nativeEvent: { layout: { width, height: 4, x: 0, y: 0 } },
    });
  });
}

it('offers one thing before anything has been heard', async () => {
  // No bar and no clock at rest, because there is no position and no length
  // yet — the file has not been asked for. A transport drawn against zeroes
  // would be reporting a measurement nobody took.
  await show({ state: 'idle' });

  expect(screen.getByRole('button', { name: 'Hear this room' })).toBeTruthy();
  expect(screen.queryByTestId('scrub')).toBeNull();
});

it('says it is looking rather than going quiet on the tap', async () => {
  // The link is signed at the moment of the tap and the file's header is read
  // over the network after that, so there is a real gap before a sound. A
  // control that simply stopped responding is the failure this prevents.
  await show({ state: 'opening' });

  const control = screen.getByRole('button', { name: 'Finding it' });
  expect(control.props.accessibilityState).toEqual(
    expect.objectContaining({ disabled: true })
  );
});

it('reads out where it is and how long the room is', async () => {
  await show({ state: 'playing', at: 247, runs: 761 });

  expect(screen.getByText('4:07')).toBeTruthy();
  expect(screen.getByText('12:41')).toBeTruthy();
});

it('says only where it is while the length is still unknown', async () => {
  // Duration arrives with the file's header and is zero until then. "4:07 of
  // 0:00" is a room that has already finished, which is a lie about the thing
  // currently making noise.
  await show({ state: 'playing', at: 247, runs: 0 });

  expect(screen.getByText('4:07')).toBeTruthy();
  expect(screen.queryByText('0:00')).toBeNull();
});

it('offers to stop while it is speaking', async () => {
  const props = await show({ state: 'playing', at: 10, runs: 100 });

  fireEvent.press(screen.getByRole('button', { name: 'Pause' }));

  expect(props.onPause).toHaveBeenCalled();
});

it('offers to go on once it is not', async () => {
  // One `render` per test, deliberately. Two roots in one body leaves `screen`
  // pointing at a tree that cleanup has already detached, and every test after
  // it then fails to find elements that are plainly there — which cost an
  // afternoon once and looks exactly like a broken component.
  const props = await show({ state: 'paused', at: 10, runs: 100 });

  fireEvent.press(screen.getByRole('button', { name: 'Play' }));

  expect(props.onPlay).toHaveBeenCalled();
});

it('goes back fifteen seconds, which is what a missed sentence costs', async () => {
  const props = await show({ state: 'playing', at: 100, runs: 600 });

  fireEvent.press(screen.getByRole('button', { name: 'Back fifteen seconds' }));

  expect(props.onSeek).toHaveBeenCalledWith(85);
});

it('will not seek behind the start of the room', async () => {
  const props = await show({ state: 'playing', at: 4, runs: 600 });

  fireEvent.press(screen.getByRole('button', { name: 'Back fifteen seconds' }));

  expect(props.onSeek).toHaveBeenCalledWith(0);
});

it('seeks to the point on the bar that was touched', async () => {
  // Twelve minutes at fifteen seconds a tap is thirty-six taps to reach the
  // end, so the bar has to be the coarse control and Back fifteen the fine one.
  const props = await show({ state: 'playing', at: 0, runs: 600 });
  await measure(300);

  fireEvent.press(screen.getByTestId('scrub'), { nativeEvent: { locationX: 150 } });

  expect(props.onSeek).toHaveBeenCalledWith(300);
});

it('does not seek against a bar it has not measured', async () => {
  // `onLayout` has not fired on the first frame. Dividing by a zero width is
  // an Infinity handed to a native seek, and the room jumps to its end.
  const props = await show({ state: 'playing', at: 0, runs: 600 });

  fireEvent.press(screen.getByTestId('scrub'), { nativeEvent: { locationX: 150 } });

  expect(props.onSeek).not.toHaveBeenCalled();
});

it('does not seek into a room whose length it does not know', async () => {
  const props = await show({ state: 'playing', at: 0, runs: 0 });
  await measure(300);

  fireEvent.press(screen.getByTestId('scrub'), { nativeEvent: { locationX: 150 } });

  expect(props.onSeek).not.toHaveBeenCalled();
});

it('names the position for somebody who cannot see the bar', async () => {
  await show({ state: 'playing', at: 247, runs: 761 });

  const bar = screen.getByTestId('scrub');
  expect(bar.props.accessibilityValue).toEqual(
    expect.objectContaining({ text: '4:07 of 12:41' })
  );
});

it('says what went wrong, and still offers the way to try it', async () => {
  // The link lives fifteen minutes and the stream is read over HTTP ranges, so
  // a failure mid-room is ordinary — and the recovery is the same tap, because
  // the next one signs a fresh link.
  const props = await show({
    state: 'failed',
    refusal: 'That did not play. Try it again in a moment.',
  });

  expect(screen.getByText('That did not play. Try it again in a moment.')).toBeTruthy();

  fireEvent.press(screen.getByRole('button', { name: 'Hear this room' }));
  expect(props.onPlay).toHaveBeenCalled();
});
