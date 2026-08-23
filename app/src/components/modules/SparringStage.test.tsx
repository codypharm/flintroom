import { render, screen, userEvent } from '@testing-library/react-native';
import { usePreventRemove } from 'expo-router/react-navigation';

// The stage guards its own removal from the stack; there is no navigator in a
// component test, so the seam is asserted through the mock instead.
jest.mock('expo-router/react-navigation', () => ({
  usePreventRemove: jest.fn(),
}));

import { SparringStage, type SparringStageProps } from './SparringStage';

/**
 * The stage: one question on the table, and a discussion with the coach.
 *
 * These tests hold the casting the architect confirmed before this was built:
 * the panelist's question is the *object* — their face, their words, what was
 * said in the room, fixed and in the past tense — and the live thread beneath
 * it is entirely coach and presenter. If the panelist ever appeared to speak
 * again here, the stage would read as a second interrogation, which is the
 * metered thing this phase deliberately is not.
 */

const ANSWER = {
  ordinal: 1,
  question: 'What does it cost you to acquire a customer, and how long until that pays back?',
  askedBy: 'cfo',
  answer:
    'Acquisition cost is twelve hundred dollars, and a customer pays us a hundred and eighty a month, so payback lands around four months.',
  weakness: 'contradicted' as const,
  why: 'At $180 a month, recovering $1,200 takes nearly seven months rather than four.',
  nextTime: 'Do the division out loud before he does it for you.',
};

const SPOKEN = 'QUJD';

async function setup(overrides: Partial<SparringStageProps> = {}) {
  const props: SparringStageProps = {
    answer: ANSWER,
    attempts: [],
    onBack: jest.fn(),
    onReplay: jest.fn(),
    ...overrides,
  };
  await render(<SparringStage {...props} />);
  return props;
}

it('puts the question on the table — who asked it, and what was said in the room', async () => {
  await setup();

  expect(screen.getByText('The CFO')).toBeTruthy();
  expect(screen.getByText(/What does it cost you to acquire a customer/)).toBeTruthy();
  expect(screen.getByText(/Acquisition cost is twelve hundred dollars/)).toBeTruthy();
  expect(screen.getByText(/recovering \$1,200 takes nearly seven months/)).toBeTruthy();
});

it('never blames the presenter for a question a panelist took away', async () => {
  // #56 travels with the finding wherever it is drawn. The stage renders the
  // same silence line the sheet does, from the same single decision.
  await setup({
    answer: { ...ANSWER, answer: null, weakness: 'dismissed', askedBy: 'champion' },
  });

  expect(screen.getByText('A panelist cut across you.')).toBeTruthy();
});

it('carries the forward half of the finding when there is one', async () => {
  await setup();

  expect(screen.getByText('Do the division out loud before he does it for you.')).toBeTruthy();
});

it('stays whole when the suggestion was dropped', async () => {
  await setup({ answer: { ...ANSWER, nextTime: null } });

  expect(screen.queryByText('Next time')).toBeNull();
  expect(screen.getByText(/recovering \$1,200 takes nearly seven months/)).toBeTruthy();
});

it('shows the discussion — your words, then what the coach said back', async () => {
  await setup({
    attempts: [
      {
        speech: SPOKEN,
        heard: 'Acquisition is twelve hundred, and we recover it in about seven months.',
        said: 'That is the arithmetic the CFO was after. Say the seven before they ask.',
      },
    ],
  });

  expect(screen.getByText(/we recover it in about seven months/)).toBeTruthy();
  expect(screen.getByText(/Say the seven before they ask/)).toBeTruthy();
});

it('offers a way back to a reply that was missed', async () => {
  const props = await setup({
    attempts: [{ speech: SPOKEN, heard: 'Seven months.', said: 'That is the figure.' }],
  });

  await userEvent.press(screen.getByLabelText('Hear that again'));

  expect(props.onReplay).toHaveBeenCalledWith(SPOKEN);
});

it('says an unworked question is unworked, without marking it failed', async () => {
  await setup();

  expect(screen.getByText('You have not answered this one again yet.')).toBeTruthy();
});

it('goes back to the findings on its own control', async () => {
  const props = await setup();

  await userEvent.press(screen.getByText('All findings'));

  expect(props.onBack).toHaveBeenCalled();
});

it('turns every kind of back into the way to the findings', async () => {
  // Android-first, and learned on a phone: a BackHandler subscription here
  // closed the stage while the native stack popped the route in the same
  // press — back went two screens — and the header's chevron was never
  // intercepted at all. Preventing the removal itself is the one seam the
  // hardware back and the chevron both pass through.
  const props = await setup();

  const guard = jest.mocked(usePreventRemove);
  expect(guard).toHaveBeenCalledWith(true, expect.any(Function));

  const [, onPrevented] = guard.mock.calls[guard.mock.calls.length - 1];
  onPrevented({ data: { action: { type: 'GO_BACK' } } });

  expect(props.onBack).toHaveBeenCalled();
});

it('runs no clock and counts nothing down', async () => {
  // The retired mockup for this surface ran 04:12 over the re-try, and a
  // clock on the one deliberately unmetered phase reads as a meter. #59 also
  // forbids a verdict, so nothing here may mark an attempt as enough.
  await setup({
    attempts: [{ speech: SPOKEN, heard: 'Seven months.', said: 'That is the figure.' }],
  });

  expect(screen.queryByText(/\d+:\d{2}/)).toBeNull();
  expect(screen.queryByText(/minute|credit|token|upgrade|remaining|left/i)).toBeNull();
  expect(screen.queryByText(/better|worse|correct|improved|good|held|passed/i)).toBeNull();
});
