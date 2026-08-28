import { render, screen, userEvent } from '@testing-library/react-native';

import { Replay } from './Replay';

/**
 * The replay control while the coach is mid-sentence — #107 item 9's second
 * half. Dimming alone read as a button that might still work; while the coach
 * speaks the control now *says* what is happening instead of offering what is
 * not, and comes back as itself when the voice stops.
 */

it('offers to replay when nothing is playing', async () => {
  await render(<Replay onReplay={jest.fn()} />);

  expect(screen.getByText('Hear that again')).toBeOnTheScreen();
});

it('says the coach is speaking instead of offering a replay mid-sentence', async () => {
  await render(<Replay onReplay={jest.fn()} disabled />);

  expect(screen.getByText('Speaking…')).toBeOnTheScreen();
  expect(screen.queryByText('Hear that again')).toBeNull();
});

it('cannot be pressed while the coach is speaking', async () => {
  // Two coach voices on one speaker is the failure this exists to prevent.
  const onReplay = jest.fn();
  await render(<Replay onReplay={onReplay} disabled />);

  await userEvent.press(screen.getByLabelText('The coach is speaking'));

  expect(onReplay).not.toHaveBeenCalled();
});

it('says it is getting the audio the moment it is pressed', async () => {
  // Field-tested 2026-08-28: the tap did its work — voice engine setup, then
  // decode — but the control sat unchanged for seconds, reading as ignored.
  const onReplay = jest.fn();
  await render(<Replay onReplay={onReplay} />);

  await userEvent.press(screen.getByText('Hear that again'));

  expect(onReplay).toHaveBeenCalled();
  expect(screen.getByText('Getting it…')).toBeOnTheScreen();
});

it('hands over from getting to speaking when the audio starts', async () => {
  const drawn = await render(<Replay onReplay={jest.fn()} />);
  await userEvent.press(screen.getByText('Hear that again'));

  await drawn.rerender(<Replay onReplay={jest.fn()} disabled />);

  expect(screen.getByText('Speaking…')).toBeOnTheScreen();
  expect(screen.queryByText('Getting it…')).toBeNull();
});

it('returns to rest when the audio has stopped', async () => {
  const drawn = await render(<Replay onReplay={jest.fn()} disabled />);

  await drawn.rerender(<Replay onReplay={jest.fn()} />);

  expect(screen.getByText('Hear that again')).toBeOnTheScreen();
});
