import { render, screen, userEvent } from '@testing-library/react-native';

import { YourPanelists } from './YourPanelists';

/**
 * The panel you wrote, and the only place it can be changed.
 *
 * Tapping a card in the setup rail *seats* that panelist, so there is no
 * gesture left on it for opening one — which is why `revise` and `retire` had
 * endpoints, service rules and a form route for two commits with nothing able
 * to reach them.
 */

const MINE = [
  {
    name: 'custom:0191d4c2',
    title: 'The Board Chair',
    persona: 'Unimpressed by anything that is not a number.',
    domains: ['margin'],
    voice: null,
  },
  {
    name: 'custom:0191d4c3',
    title: 'The Regulator',
    persona: 'Asks which approval you skipped.',
    domains: ['compliance'],
    voice: 'brisk',
  },
];

async function show(over: Partial<Parameters<typeof YourPanelists>[0]> = {}) {
  const user = userEvent.setup();
  const onEdit = jest.fn();
  const onRetire = jest.fn();
  const onWrite = jest.fn();

  await render(
    <YourPanelists
      mine={MINE}
      busy={null}
      refusal={null}
      onEdit={onEdit}
      onRetire={onRetire}
      onWrite={onWrite}
      {...over}
    />
  );

  return { user, onEdit, onRetire, onWrite };
}

it('lists them by the name their author gave them', async () => {
  await show();

  expect(screen.getByText('The Board Chair')).toBeTruthy();
  expect(screen.getByText('The Regulator')).toBeTruthy();
});

it('opens one for editing', async () => {
  const { user, onEdit } = await show();

  await user.press(screen.getByLabelText('Edit The Board Chair'));

  expect(onEdit).toHaveBeenCalledWith('custom:0191d4c2');
});

it('says remove, never delete', async () => {
  // §4 — the row stays so every past room can still say who was in it, and
  // account deletion is the real delete. A control saying "delete" would be the
  // product claiming something `docs/privacy-policy.md` cannot.
  await show();

  expect(screen.getByLabelText('Remove The Board Chair from your panel')).toBeTruthy();
  expect(screen.queryByText(/delete/i)).toBeNull();
});

it('says what removing does and does not do, before it is done', async () => {
  const { user } = await show();

  await user.press(screen.getByLabelText('Remove The Board Chair from your panel'));

  expect(screen.getByText(/rooms .* still/i)).toBeTruthy();
});

it('removes only once the second tap confirms it', async () => {
  // One tap is how somebody loses a panelist they spent ten minutes on.
  const { user, onRetire } = await show();

  await user.press(screen.getByLabelText('Remove The Board Chair from your panel'));
  expect(onRetire).not.toHaveBeenCalled();

  await user.press(screen.getByLabelText('Yes, remove them'));
  expect(onRetire).toHaveBeenCalledWith('custom:0191d4c2');
});

it('lets a confirmation be backed out of', async () => {
  const { user, onRetire } = await show();

  await user.press(screen.getByLabelText('Remove The Board Chair from your panel'));
  await user.press(screen.getByLabelText('Keep them'));

  expect(onRetire).not.toHaveBeenCalled();
  expect(screen.getByText('The Board Chair')).toBeTruthy();
});

it('offers to write another', async () => {
  const { user, onWrite } = await show();

  await user.press(screen.getByLabelText('Write another panelist'));

  expect(onWrite).toHaveBeenCalled();
});

it('reads as a beginning rather than an error when there are none', async () => {
  await show({ mine: [] });

  expect(screen.getByLabelText('Write another panelist')).toBeTruthy();
  expect(screen.queryByText(/no panelists|empty|nothing here/i)).toBeNull();
});

it('locks the row being removed rather than the whole screen', async () => {
  // A slow request on one panelist should not stop somebody editing another.
  const { user, onEdit } = await show({ busy: 'custom:0191d4c2' });

  await user.press(screen.getByLabelText('Edit The Regulator'));

  expect(onEdit).toHaveBeenCalledWith('custom:0191d4c3');
});

it('says a refusal out loud', async () => {
  await show({ refusal: 'We could not remove that one.' });

  expect(screen.getByRole('alert')).toBeTruthy();
});
