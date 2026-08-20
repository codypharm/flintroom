import { render, screen, userEvent } from '@testing-library/react-native';

/**
 * `userEvent` rather than `fireEvent`, and it is not a preference.
 *
 * This form holds its own state, and under React 19 a `fireEvent` update is
 * scheduled but not flushed before the next assertion — so every interaction
 * appeared to do nothing and the save button stayed disabled through a
 * completely filled form. `fireEvent` still works where a press only calls a
 * prop, which is why `TablePlan` uses it; anything that has to *see* the result
 * of its own typing needs the async one.
 */

import { PanelistForm } from './PanelistForm';

/**
 * Writing a panelist.
 *
 * `design-guide/create_custom_panelist/` gave the layout and none of the
 * fields: it asks for Panelist Name, Core Focus, **Investment Stage**, Feedback
 * Tone and an "AI investor" persona, which is the retired pitch-only product.
 * What survives is the shape — back and title, labelled sections, a textarea for
 * the long field, small choices as segmented rows, one action at the foot.
 */

const DOMAINS = [
  { name: 'margin', label: 'Margin' },
  { name: 'runway', label: 'Runway' },
  { name: 'defensibility', label: 'What stops a copy' },
  { name: 'feasibility', label: 'Whether it works' },
];
const VOICES = [
  {
    name: 'measured',
    label: 'Measured',
    sounds: 'Unhurried and formal. Says less than it could.',
  },
  { name: 'brisk', label: 'Brisk', sounds: 'Clipped and impatient.' },
];

async function show(over: Partial<Parameters<typeof PanelistForm>[0]> = {}) {
  const user = userEvent.setup();
  const onSave = jest.fn();
  const onCancel = jest.fn();

  await render(
    <PanelistForm
      domains={DOMAINS}
      voices={VOICES}
      existing={null}
      busy={false}
      refusal={null}
      onSave={onSave}
      onCancel={onCancel}
      {...over}
    />
  );

  return { user, onSave, onCancel };
}

async function fill(
  user: ReturnType<typeof userEvent.setup>,
  over: { title?: string; persona?: string; domain?: string } = {}
) {
  await user.type(
    screen.getByLabelText('Role'),
    over.title ?? 'The Board Chair'
  );
  await user.type(
    screen.getByLabelText('Manner'),
    over.persona ?? 'Unimpressed by anything that is not a number.'
  );
  await user.press(screen.getByLabelText(over.domain ?? 'Margin'));
}

it('sends what was typed, with the domains that were tapped', async () => {
  const { user, onSave } = await show();

  await fill(user);
  await user.press(screen.getByLabelText('Save this panelist'));

  expect(onSave).toHaveBeenCalledWith({
    title: 'The Board Chair',
    persona: 'Unimpressed by anything that is not a number.',
    domains: ['margin'],
    voice: null,
  });
});

it('will not save a panelist with nothing to go after', async () => {
  // Domains are the Auditor's routing key. One with none can never be the
  // panelist an interruption reaches, and its author would never find out why —
  // so the form refuses before the server has to.
  const { user, onSave } = await show();

  await user.type(screen.getByLabelText('Role'), 'X');
  await user.type(screen.getByLabelText('Manner'), 'Y');
  await user.press(screen.getByLabelText('Save this panelist'));

  expect(onSave).not.toHaveBeenCalled();
});

it('will not save one with no name or nobody in it', async () => {
  const { user, onSave } = await show();

  await user.press(screen.getByLabelText('Save this panelist'));

  expect(onSave).not.toHaveBeenCalled();
});

it('offers a voice but never demands one', async () => {
  // "Pick one for me" is the default, and it is what an untouched form sends.
  // Casting is a decision tax on the feature's main path.
  const { user, onSave } = await show();

  await fill(user);
  await user.press(screen.getByLabelText('Save this panelist'));

  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ voice: null }));
});

it('says what a voice sounds like, because the names do not', async () => {
  await show();

  expect(screen.getByText(/Unhurried and formal/)).toBeTruthy();
});

it('carries a chosen voice through', async () => {
  const { user, onSave } = await show();

  await fill(user);
  await user.press(screen.getByLabelText('Brisk. Clipped and impatient.'));
  await user.press(screen.getByLabelText('Save this panelist'));

  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ voice: 'brisk' }));
});

it('offers only domains the server routes on', async () => {
  // Never a free-text field. A domain we do not route on is refused by the API,
  // so offering one would put the refusal on somebody who picked what we showed.
  await show();

  for (const domain of DOMAINS) {
    expect(screen.getByLabelText(domain.label)).toBeTruthy();
  }
  expect(screen.queryByLabelText(/Core Focus/i)).toBeNull();
});

it('names a domain in words rather than showing its identifier', async () => {
  // `defensibility` on a chip is a column name on a screen. The audience knows
  // `margin` and `runway` — flattening those would be worse — but nobody can
  // rank `proof`, `references` and `resilience` against each other on sight.
  await show();

  expect(screen.getByText('What stops a copy')).toBeTruthy();
  expect(screen.queryByText('defensibility')).toBeNull();
});

it('says what is still missing rather than sitting there disabled', async () => {
  // The setup screen already does this: "a sentence rather than a boolean,
  // because a disabled button with no reason is the failure this exists to
  // prevent." The same product had one screen explaining itself and this one
  // saying nothing at all.
  const { user } = await show();

  await user.type(screen.getByLabelText('Role'), 'The Chair');

  // Exact, not a substring: the second field's hint ends "...all they will know
  // about who they are", and a loose match would pass on the helper text while
  // the shortfall line was missing entirely.
  expect(screen.getByText('Describe the manner.')).toBeTruthy();
});

it('stops saying it the moment there is nothing missing', async () => {
  const { user } = await show();

  await fill(user);

  expect(screen.queryByText(/still needs/i)).toBeNull();
});

it('says the length limit before it is hit, not after', async () => {
  // The server caps the persona and answers 422. Without a limit here that
  // arrives as "that did not save", which names neither the field nor the
  // reason — a requirement stated after submission, which is the thing forms
  // are supposed to avoid.
  await show();

  const field = screen.getByLabelText('Manner');

  expect(field.props.maxLength).toBe(400);
});

it('reopens an existing panelist with its own words in it', async () => {
  await show({
    existing: {
      name: 'custom:0191d4c2',
      title: 'The Regulator',
      persona: 'Asks which approval you skipped.',
      domains: ['compliance'],
      voice: 'brisk',
    },
  });

  expect(screen.getByLabelText('Role').props.value).toBe(
    'The Regulator'
  );
  expect(screen.getByLabelText('Manner').props.value).toBe(
    'Asks which approval you skipped.'
  );
});

it('locks the form while it is being saved', async () => {
  const { user, onSave } = await show({ busy: true });

  await fill(user);
  await user.press(screen.getByLabelText('Save this panelist'));

  expect(onSave).not.toHaveBeenCalled();
});

it('says a refusal out loud rather than only colouring it', async () => {
  await show({ refusal: 'You already have a panelist with that name.' });

  expect(screen.getByRole('alert')).toBeTruthy();
});

it('never asks for a photograph', async () => {
  // The mockup has an Upload Photo control. Portraits are "generated people,
  // not photographs of anyone", which portraits.ts calls the whole reason they
  // are permissible — an upload is the right-of-publicity exposure the project
  // rejected wholesale. A custom panelist wears its own initials.
  await show();

  expect(screen.queryByLabelText(/photo|upload|picture/i)).toBeNull();
});

it('never asks a question this product does not have', async () => {
  // Investment Stage and Feedback Tone are the retired pitch-only product, and
  // a field is a promise the same way a picker option is.
  await show();

  expect(screen.queryByText(/investment|stage|tone|template/i)).toBeNull();
});

it('labels the fields with nouns rather than questions', async () => {
  // Four questions in a row said "they" four times, one screen from "Your
  // panelists", and read as configuring a group rather than writing one person.
  // A noun label needs no pronoun at all — which also makes the form four words
  // to scan instead of four sentences to read.
  await show();

  for (const label of ['Role', 'Manner', 'Focus', 'Voice']) {
    expect(screen.getByText(label)).toBeTruthy();
  }
  expect(screen.queryByText(/\?$/)).toBeNull();
});
