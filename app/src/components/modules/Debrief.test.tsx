import { render, screen, userEvent } from '@testing-library/react-native';

import { Debrief, type DebriefProps } from './Debrief';

/**
 * The unmetered half of the product, and the first surface it has ever had.
 *
 * These tests hold the product truth the composition sits on: that this sheet
 * accumulates work rather than scoring it, that nothing here can be mistaken
 * for a verdict or a meter, that talking is never gated behind picking a
 * question, and that the fault split #56 settled is not quietly re-pooled by a
 * layout which lists every finding together.
 */

const ANSWERS = [
  {
    ordinal: 1,
    question: 'What does it cost you to acquire a customer, and how long until that pays back?',
    askedBy: 'cfo',
    answer:
      'Acquisition cost is twelve hundred dollars, and a customer pays us a hundred and eighty a month, so payback lands around four months.',
    weakness: 'contradicted' as const,
    why: 'At $180 a month, recovering $1,200 takes nearly seven months rather than four.',
  },
  {
    ordinal: 5,
    question: 'How long does it take a new customer to see value?',
    askedBy: 'champion',
    answer: null,
    weakness: 'dismissed' as const,
    why: 'Another panelist interrupted with a question about burn before you could answer.',
  },
];

async function setup(overrides: Partial<DebriefProps> = {}) {
  const props: DebriefProps = {
    answers: ANSWERS,
    pressed: null,
    thread: [],
    attempts: {},
    listening: { state: 'idle' },
    refusal: null,
    onTalk: jest.fn(),
    onStop: jest.fn(),
    onPrepSheet: jest.fn(),
    ...overrides,
  };
  await render(<Debrief {...props} />);
  return props;
}

it('opens on what came loose, worst first, without a score anywhere', async () => {
  // The ranking is a model's judgement made with the whole room in view (#57),
  // so it is rendered in the order it arrived. What must never appear is a
  // number standing for how the session went: a grade on this screen is the
  // delivery-metrics product §1 exists to refuse, and the retired mockup for
  // this surface opened with a "B+".
  await setup();

  expect(screen.getByText('Where it came loose')).toBeTruthy();

  const questions = screen.getAllByLabelText(/^Question from/);
  expect(questions).toHaveLength(2);
  expect(screen.getByText(/What does it cost you to acquire a customer/)).toBeTruthy();
});

it('says how the room compared with the last one, in words', async () => {
  // #55's remaining half. `DebriefRead.pressed` carries the fact and the client
  // writes the sentence — never the level, because a rung on screen is a score.
  await setup({ pressed: 'harder' });

  expect(screen.getByText('They pressed harder this time than last.')).toBeTruthy();
});

it('says nothing at all when the room did not move', async () => {
  // Null is not "the same". `docs/difficulty-calibration.md` decision 5 keeps
  // the dial quiet unless it moved, so a user who cannot tell the room changed
  // is not told it did.
  await setup({ pressed: null });

  expect(screen.queryByText(/pressed harder/)).toBeNull();
  expect(screen.queryByText(/went easier/)).toBeNull();
});

it('carries the presenter’s own words back, not a category', async () => {
  // `WeakAnswerRead` exists in this shape deliberately: a response of verdicts
  // alone would be a scorecard. The sheet's whole structure is what was said in
  // the room against what is said now.
  await setup();

  expect(
    screen.getByText(/Acquisition cost is twelve hundred dollars/)
  ).toBeTruthy();
  expect(
    screen.getByText(/recovering \$1,200 takes nearly seven months/)
  ).toBeTruthy();
});

it('never blames the presenter for a question a panelist took away', async () => {
  // #56, and the one thing on this screen that must not be got wrong. Both of
  // these went unanswered; only one is the user's doing. A list that showed the
  // same empty slot for each would be the accusation #56 exists to prevent,
  // arriving through a layout instead of a sentence.
  await setup();

  expect(screen.getByText('A panelist cut across you.')).toBeTruthy();
  expect(screen.queryByText(/you let it go/i)).toBeNull();
});

it('shows an unworked question as unworked, without marking it failed', async () => {
  // The empty slot is the sheet's whole device, and it must read as "not yet"
  // rather than as a box left unticked. Nothing here is scored, so nothing here
  // can be incomplete.
  await setup();

  expect(screen.getAllByText('You have not answered this one again yet.')).toHaveLength(2);
});

it('fills a question in with what was heard and what the coach said back', async () => {
  // The accumulation. Both halves are shown: `heard` because a transcription
  // error is otherwise indistinguishable from the coach missing the point, and
  // the reply because #59's coach says what *changed* rather than whether it
  // was good enough.
  await setup({
    attempts: {
      0: [
        {
          heard: 'Acquisition is twelve hundred, and we recover it in about seven months.',
          said: 'That is the arithmetic the CFO was after. Say the seven before they ask.',
        },
      ],
    },
  });

  expect(
    screen.getByText(/we recover it in about seven months/)
  ).toBeTruthy();
  expect(screen.getByText(/Say the seven before they ask/)).toBeTruthy();
  expect(screen.getAllByText('You have not answered this one again yet.')).toHaveLength(1);
});

it('never says whether a re-answer was good enough', async () => {
  // §3.5's re-try loop and #59's hardest constraint: no verdict, ever. Telling
  // somebody a thin answer landed sends them into the real room believing it,
  // which is the single outcome this loop exists to prevent. The user decides
  // when to stop.
  await setup({
    attempts: { 0: [{ heard: 'Seven months.', said: 'That is the figure.' }] },
  });

  expect(screen.queryByText(/better|worse|correct|improved|good/i)).toBeNull();
  expect(screen.queryByLabelText(/passed|failed|complete/i)).toBeNull();
});

it('answers one question again, addressed by its rank', async () => {
  // Anchored by rank because `docs/debrief-and-sparring.md` decision 4 requires
  // it: a re-answer is fresh speech, and only a stored rank makes "spar me on
  // this instead" unexpressible.
  const props = await setup();

  await userEvent.press(screen.getAllByText('Answer it again')[1]);

  expect(props.onTalk).toHaveBeenCalledWith(1);
});

it('lets somebody talk without picking a question first', async () => {
  // The sheet is the record; the conversation is free. `CLAUDE.md` forbids
  // reducing the coach to a form-filling flow, and gating speech behind an
  // entry is exactly how a sheet becomes a form.
  const props = await setup();

  await userEvent.press(screen.getByText('Talk to me'));

  expect(props.onTalk).toHaveBeenCalledWith(null);
});

it('shows a coaching turn that belonged to no question at the foot', async () => {
  await setup({
    thread: [
      {
        heard: 'Which of these should I fix first?',
        said: 'The payback figure. It is the one two of them will both come back to.',
      },
    ],
  });

  expect(screen.getByText(/Which of these should I fix first/)).toBeTruthy();
  expect(screen.getByText(/It is the one two of them will both come back to/)).toBeTruthy();
});

it('says it is listening, and offers the way to stop', async () => {
  // Tap to start, tap to stop. The elapsed count is here because a recording
  // with no visible length is one somebody leaves running, and the ceiling is a
  // refusal rather than a warning.
  const props = await setup({ listening: { state: 'listening', seconds: 12, at: null } });

  expect(screen.getByText('0:12')).toBeTruthy();

  await userEvent.press(screen.getByText('Done'));
  expect(props.onStop).toHaveBeenCalled();
});

it('cannot be told to listen twice at once', async () => {
  // Reachable by tapping a question's re-try while a general turn is recording.
  // Two live captures would send the second clip against whichever request
  // finished last, which is a re-answer landing on the wrong question.
  const props = await setup({ listening: { state: 'listening', seconds: 3, at: null } });

  await userEvent.press(screen.getAllByText('Answer it again')[0]);

  expect(props.onTalk).not.toHaveBeenCalled();
});

it('names a refusal in the sheet rather than replacing it', async () => {
  // A turn that failed does not invalidate the room. Swapping the sheet for an
  // error would throw away the findings somebody is working through because one
  // clip did not transcribe.
  await setup({ refusal: 'I didn’t catch anything there — try again.' });

  expect(screen.getByText('I didn’t catch anything there — try again.')).toBeTruthy();
  expect(screen.getByText('Where it came loose')).toBeTruthy();
});

it('offers the prep sheet as the way out', async () => {
  const props = await setup();

  await userEvent.press(screen.getByText('Your prep sheet'));

  expect(props.onPrepSheet).toHaveBeenCalled();
});

it('never mentions minutes, cost, or an upgrade', async () => {
  // §4.1's boundary, rendered. The debrief and sparring are unmetered, and
  // `CLAUDE.md` forbids a paywall or a depleting counter here. The retired
  // mockup for this screen carried a token count and a running timer; both
  // would read as a meter on the one phase that has none.
  await setup({ attempts: { 0: [{ heard: 'Seven months.', said: 'That is it.' }] } });

  expect(screen.queryByText(/minute|credit|token|upgrade|remaining|left/i)).toBeNull();
});

it('says a clean room went well instead of drawing an empty list', async () => {
  // An empty list is a real answer, not a failure — and the coach still works,
  // because the transcript is still there to be asked about.
  await setup({ answers: [] });

  expect(screen.getByText('Nothing came loose')).toBeTruthy();
  expect(screen.getByText('Talk to me')).toBeTruthy();
});
