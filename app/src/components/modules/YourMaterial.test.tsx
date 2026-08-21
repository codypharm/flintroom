import { render, screen, userEvent } from '@testing-library/react-native';

import type { AttachedMaterial } from '../../lib/api/materialsApi';
import { YourMaterial } from './YourMaterial';

/**
 * Everything this account has attached, and the only place it can be destroyed.
 *
 * It exists because `docs/privacy-policy.md` says *"Delete attached material.
 * Any time, in Settings"* and no such control existed anywhere. The endpoint
 * shipped with #30; what was missing until #85 was any way to learn a material
 * id, so the delete was reachable only by a caller still holding the response
 * that registered it.
 */

const DECK: AttachedMaterial = {
  id: 'm1',
  filename: 'q3-board-deck.pdf',
  state: 'ready',
};

async function show(
  mine: AttachedMaterial[] = [DECK],
  props: Partial<Parameters<typeof YourMaterial>[0]> = {}
) {
  const onDelete = jest.fn();
  await render(
    <YourMaterial mine={mine} busy={null} refusal={null} onDelete={onDelete} {...props} />
  );
  return { onDelete };
}

it('names each file, because the name is the only thing that identifies it', async () => {
  // The source document is deleted once extraction succeeds, so the filename
  // and a thumbnail are all that is left to recognise a deck by. Somebody about
  // to destroy one has to be able to tell which.
  await show();

  expect(screen.getByText('q3-board-deck.pdf')).toBeOnTheScreen();
});

it('says what state each one is in, in the words the setup screen uses', async () => {
  await show([
    { id: 'm1', filename: 'a.pdf', state: 'ready' },
    { id: 'm2', filename: 'b.pdf', state: 'extracting' },
    { id: 'm3', filename: 'c.pdf', state: 'failed' },
  ]);

  expect(screen.getByText(/ready to be used against you/i)).toBeOnTheScreen();
  expect(screen.getByText(/being read/i)).toBeOnTheScreen();
  expect(screen.getByText(/could not be read/i)).toBeOnTheScreen();
});

it('asks before destroying one, and says what destroying it does not do', async () => {
  /**
   * The fear is losing the rooms. It is a real consequence of a different
   * shape: the transcripts stay, and a *re-run* of one of those rooms will no
   * longer be grounded in this material — which is exactly what
   * `materialsApi.read` already anticipates ("a re-run should then offer the
   * panel without the material rather than a room grounded in nothing").
   *
   * In place rather than in a native alert, as `YourPanelists` decided for the
   * same reason: the sentence worth reading is the one about what survives,
   * and an alert body is where that goes to be dismissed unread.
   */
  const { onDelete } = await show();

  await userEvent.press(screen.getByLabelText('Delete q3-board-deck.pdf'));

  expect(screen.getByText(/rooms it was in are still here/i)).toBeOnTheScreen();
  expect(onDelete).not.toHaveBeenCalled();
});

it('destroys it only on the second, explicit tap', async () => {
  const { onDelete } = await show();

  await userEvent.press(screen.getByLabelText('Delete q3-board-deck.pdf'));
  await userEvent.press(screen.getByLabelText('Yes, delete it'));

  expect(onDelete).toHaveBeenCalledWith('m1');
});

it('lets somebody back out of a deletion they opened', async () => {
  const { onDelete } = await show();

  await userEvent.press(screen.getByLabelText('Delete q3-board-deck.pdf'));
  await userEvent.press(screen.getByLabelText('Keep it'));

  expect(screen.queryByText(/rooms it was in are still here/i)).not.toBeOnTheScreen();
  expect(onDelete).not.toHaveBeenCalled();
});

it('locks only the row it is working on', async () => {
  // One slow delete must not freeze the rest of the list. `YourPanelists` takes
  // the same shape and for the same reason.
  await show([DECK, { id: 'm2', filename: 'other.pdf', state: 'ready' }], {
    busy: 'm1',
  });

  expect(screen.getByLabelText('Delete q3-board-deck.pdf').props.accessibilityState)
    .toMatchObject({ disabled: true });
  expect(screen.getByLabelText('Delete other.pdf').props.accessibilityState)
    .toMatchObject({ disabled: false });
});

it('shows the refusal the server explained rather than a generic failure', async () => {
  // `material_in_use` has a specific recovery — end the room you are in — and
  // the server writes that sentence. This screen's job is to carry it.
  await show([DECK], {
    refusal: 'That material is in a room you are still in. End the session first.',
  });

  expect(screen.getByText(/end the session first/i)).toBeOnTheScreen();
});

it('says plainly that nothing is attached, and where attaching happens', async () => {
  /**
   * Different from `YourPanelists`, which deliberately has no empty state
   * because it carries the control that fills it. Nothing is attached from
   * here — a deck is attached while setting up a room — so an empty list with
   * no explanation is a dead end.
   */
  await show([]);

  expect(screen.getByText(/nothing attached/i)).toBeOnTheScreen();
  expect(screen.getByText(/set up a room/i)).toBeOnTheScreen();
});
