import { fireEvent, render, screen } from '@testing-library/react-native';

import { DeckAttach } from './DeckAttach';

/**
 * The one control on setup that reaches outside the app.
 *
 * What it replaced was a text row identical in every visual respect to the
 * archetype rows above it — same card, same two lines of type, no icon, no
 * chevron, nothing. Tapping one seated a panelist; tapping the other opened the
 * operating system. These tests are mostly about that: the states have to be
 * distinguishable, and the actions have to exist.
 */

async function show(over: Partial<Parameters<typeof DeckAttach>[0]> = {}) {
  const onAttach = jest.fn();
  const onRemove = jest.fn();

  await render(
    <DeckAttach
      material={null}
      limits={null}
      onAttach={onAttach}
      onRemove={onRemove}
      {...over}
    />
  );

  return { onAttach, onRemove };
}

const DECK = { id: 'm-1', filename: 'Q3 board deck.pdf', state: 'ready' as const };

it('says what it accepts before anybody opens a picker', async () => {
  // The picker filters, so a wrong file cannot be chosen — but somebody holding
  // a Keynote export needs to know that before they go looking for it, not
  // after the sheet shows them an empty folder.
  await show({
    limits: {
      tier: 'free',
      maxUploadBytes: 25 * 1024 * 1024,
      maxPagesPerMaterial: 40,
      acceptedContentTypes: ['application/pdf'],
    },
  });

  expect(screen.getByText(/PDF or PowerPoint/)).toBeTruthy();
  expect(screen.getByText(/25 MB/)).toBeTruthy();
});

it('still names the formats when the limits never arrived', async () => {
  // A failed limits call must not leave the one legible constraint blank. The
  // formats are a fact about the product; only the numbers come from the tier.
  await show();

  expect(screen.getByText(/PDF or PowerPoint/)).toBeTruthy();
  expect(screen.queryByText(/MB/)).toBeNull();
});

it('says a tap opens something, in the way the rest of the screen says it', async () => {
  // Reported from a device: the tappable parts of this screen do not read as
  // tappable. This card is the worst of them — the whole face is the target,
  // and it carried a title, a subtitle and a page mark drawn in `hairline` at
  // **1.70:1** against the card it sits on. Nothing on it was above the WCAG
  // 2.2 non-text floor, and nothing on it said "button".
  //
  // A chevron, because `AuthorRow` two inches down this same screen already
  // decided that is what a full-width row does when it opens something — and
  // its own note says the inverse of the rule it followed: a row that became a
  // control and kept looking like a caption.
  await show({ material: null });

  expect(screen.getByTestId('deck-open')).toBeTruthy();
});

it('draws no such promise once the face is no longer a target', async () => {
  // With a deck attached the face stops being a button — Replace and Remove
  // carry the actions instead — so a chevron there would be the lie
  // `TablePlan` refuses on its date row: an affordance on a statement.
  await show({ material: { id: 'm1', filename: 'Q3.pdf', state: 'ready' } });

  expect(screen.queryByTestId('deck-open')).toBeNull();
});

it('offers no attach target when a deck is already attached', async () => {
  // Replace exists for that. Two ways to do one thing on a row this small is
  // how somebody attaches a second deck believing they swapped the first.
  await show({ material: DECK });

  expect(screen.queryByLabelText('Attach a deck')).toBeNull();
  expect(screen.getByLabelText('Replace this deck')).toBeTruthy();
});

it('lets an attached deck be taken off again', async () => {
  // Not a local variable: the material outlives this screen and a session can
  // still be grounded in it, so the row that says it is gone has to mean it.
  const { onRemove } = await show({ material: DECK });

  fireEvent.press(screen.getByLabelText('Remove this deck'));

  expect(onRemove).toHaveBeenCalled();
});

it('shows the deck is being read, and says so out loud', async () => {
  // Three seconds a poll with a static sentence is indistinguishable from a
  // screen that has stopped. Something has to be moving.
  await show({ material: { ...DECK, state: 'extracting' } });

  expect(screen.getByLabelText('Reading your deck')).toBeTruthy();
  expect(screen.getByText(/Being read/)).toBeTruthy();
});

it('can still take a deck off while it is being read', async () => {
  // The commonest reason to want it gone is realising it is the wrong file,
  // and that realisation arrives during the wait.
  const { onRemove } = await show({ material: { ...DECK, state: 'extracting' } });

  fireEvent.press(screen.getByLabelText('Remove this deck'));

  expect(onRemove).toHaveBeenCalled();
});

it('announces a deck that could not be read, rather than only greying it', async () => {
  await show({ material: { ...DECK, state: 'failed' } });

  expect(screen.getByRole('alert')).toBeTruthy();
  expect(screen.getByText(/Could not be read/)).toBeTruthy();
});

it('names the file it is talking about', async () => {
  await show({ material: DECK });

  expect(screen.getByText('Q3 board deck.pdf')).toBeTruthy();
});
