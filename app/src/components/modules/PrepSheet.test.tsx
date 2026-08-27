import { render, screen, userEvent } from '@testing-library/react-native';

import { PrepSheet, type WeakAnswer } from './PrepSheet';

/**
 * The prep sheet, as the last thing somebody reads before the room that matters.
 *
 * The surface brief (`.impeccable/surfaces/app-src-app-prep-sheet-tsx.md`) leads
 * with the *pattern* rather than a ranked list: six items is a list you skim,
 * one habit is something you carry. These tests are about what the screen
 * states, what it refuses to state, and what it lets somebody do. Composition
 * belongs to the brief.
 */

function answer(over: Partial<WeakAnswer> = {}): WeakAnswer {
  return {
    ordinal: 1,
    question: 'Off what base, and at what cost?',
    askedBy: 'cfo',
    answer: 'We are really pleased with the trajectory.',
    weakness: 'evasive',
    why: 'You answered with a feeling about the trend, not a base.',
    nextTime: 'Lead with the base, then the cost.',
    ...over,
  };
}

async function show(answers: WeakAnswer[], props = {}) {
  await render(
    <PrepSheet
      answers={answers}
      onSpar={jest.fn()}
      onShare={jest.fn()}
      {...props}
    />
  );
}

it('opens with the kind of trouble rather than the first question', async () => {
  /**
   * The direction, asserted at its most basic. Somebody in the last hour cannot
   * act on six separate items; they can act on "you dodge when you don't have
   * the number". If the first thing on the screen is a question, this became the
   * ranked list it was deliberately not.
   */
  await show([
    answer({ ordinal: 1, weakness: 'evasive' }),
    answer({ ordinal: 3, weakness: 'evasive', question: 'And latency at ten times load?' }),
    answer({ ordinal: 5, weakness: 'unsupported', question: 'Who sponsors this?' }),
  ]);

  expect(screen.getByText(/answered a different question/i)).toBeOnTheScreen();
  expect(screen.getByText(/twice/i)).toBeOnTheScreen();
});

it('keeps what is theirs apart from what is not', async () => {
  /**
   * The load-bearing rule, and the reason the brief calls the spine "fault".
   *
   * `dismissed` means a panelist cut across them and `not_reached` means the
   * clock ran out — neither is the presenter's doing. Pooling those with
   * `evasive` would tell somebody they failed three times when they failed once,
   * and would undo #56, which exists precisely so this product never accuses
   * anybody of ducking a question that was taken away from them.
   *
   * Anchored regexes, and not fussiness: "on you" is a substring of "not on
   * you", so an unanchored match would find the second heading and call it the
   * first — and the test below, which asserts the first heading is *absent*,
   * would then pass for a screen showing exactly the accusation it forbids.
   */
  await show([
    answer({ ordinal: 1, weakness: 'evasive' }),
    answer({ ordinal: 3, weakness: 'dismissed', question: 'How long to see value?', answer: null }),
    answer({ ordinal: 5, weakness: 'not_reached', question: 'What stops a competitor?', answer: null }),
  ]);

  expect(screen.getByText(/^on you$/i)).toBeOnTheScreen();
  expect(screen.getByText(/^not on you$/i)).toBeOnTheScreen();
  // The heading clears the blame; this is what keeps them on the sheet at all.
  expect(screen.getByText(/still be asked/i)).toBeOnTheScreen();
});

it('never counts the room against the presenter', async () => {
  /**
   * A count is a claim. Three findings of which two were not theirs is "once",
   * and any headline number that says three is an accusation the product cannot
   * support — the exact failure #56 was filed to prevent, arriving through
   * arithmetic instead of through wording.
   */
  await show([
    answer({ ordinal: 1, weakness: 'evasive' }),
    answer({ ordinal: 3, weakness: 'dismissed', answer: null }),
    answer({ ordinal: 5, weakness: 'not_reached', answer: null }),
  ]);

  expect(screen.queryByText(/3 (weak|things|answers)/i)).toBeNull();
  expect(screen.queryByText(/three (weak|things|answers)/i)).toBeNull();
});

it('shows the question and hides the answer until asked', async () => {
  /**
   * The interaction the whole screen exists for. A question shown beside the
   * answer that failed it is a document to read; a question shown alone is a
   * prompt to answer out loud, which is the only thing that rebuilds an answer
   * in the last hour.
   */
  await show([answer()]);

  expect(screen.getByText(/off what base/i)).toBeOnTheScreen();
  expect(screen.queryByText(/really pleased with the trajectory/i)).toBeNull();

  await userEvent.press(screen.getByRole('button', { name: /off what base/i }));

  expect(screen.getByText(/really pleased with the trajectory/i)).toBeOnTheScreen();
});

it('offers the re-try on a question, not on the summary', async () => {
  /**
   * Principle 4: always route into rebuilding the answer. Sparring is anchored
   * to one weak answer by rank (#59), so the control belongs where that anchor
   * is unambiguous — on the question, once it is open.
   */
  const onSpar = jest.fn();
  await show([answer()], { onSpar });

  await userEvent.press(screen.getByRole('button', { name: /off what base/i }));
  await userEvent.press(screen.getByRole('button', { name: /answer it again/i }));

  expect(onSpar).toHaveBeenCalledWith(0);
});

it('says nothing was found without apologising for it', async () => {
  /**
   * A clean room is a real outcome, not an empty state. Rendering a zero, or a
   * placeholder built for a list, would read as a screen that failed rather than
   * as a session that went well.
   */
  await show([]);

  expect(screen.getByText(/nothing/i)).toBeOnTheScreen();
  expect(screen.queryByText(/^0$/)).toBeNull();
});

it('renders a room where nothing was theirs without an empty accusation', async () => {
  /**
   * Every finding was a dismissal or the clock. The "what you did" heading must
   * not appear as an empty group with a zero beside it — that is the accusation
   * again, made by a layout rather than by a sentence.
   */
  await show([
    answer({ ordinal: 1, weakness: 'dismissed', answer: null }),
    answer({ ordinal: 3, weakness: 'not_reached', answer: null }),
  ]);

  expect(screen.getByText(/^not on you$/i)).toBeOnTheScreen();
  expect(screen.queryByText(/^on you$/i)).toBeNull();
});

it('carries what to reach for into the room, not only what went wrong', async () => {
  // The sheet somebody has open on their phone in the corridor. §3.5 calls it
  // "the 6 questions you will get, and where your answers are thin" — and the
  // sentence worth having there at that moment is the one that says what to do
  // about it, which until 2026-08-20 existed nowhere.
  await show([answer()]);

  await userEvent.press(screen.getAllByRole('button')[0]);

  expect(screen.getAllByText('Lead with the base, then the cost.').length).toBeGreaterThan(0);
});

describe('the sheet as it leaves the phone', () => {
  /**
   * #60 named the export from the start: render the sheet to an image, hand
   * it to the native share sheet, and drop the verbatim answers on the way
   * out. The route captures a `printing` render for exactly that — the
   * findings expanded so the image needs no taps, the fumbled words absent
   * so what leaves the phone is the questions and the coaching, and no
   * controls, because a button in a picture is a lie about what a tap does.
   */
  it('shows the finding open, without needing a tap', async () => {
    await show([answer()], { printing: true });

    expect(screen.getByText('You answered with a feeling about the trend, not a base.')).toBeTruthy();
    expect(screen.getByText('Lead with the base, then the cost.')).toBeTruthy();
  });

  it('never carries what was actually said', async () => {
    await show([answer()], { printing: true });

    expect(screen.queryByText('We are really pleased with the trajectory.')).toBeNull();
    expect(screen.queryByText('You said')).toBeNull();
  });

  it('carries no controls into the picture', async () => {
    await show([answer()], { printing: true });

    expect(screen.queryByText('Share this sheet')).toBeNull();
    expect(screen.queryByText('Answer it again')).toBeNull();
    expect(screen.queryByText(/The coach/)).toBeNull();
  });
});
