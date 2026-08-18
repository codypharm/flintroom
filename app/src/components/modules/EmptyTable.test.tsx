import { render, screen } from '@testing-library/react-native';

import { EmptyTable } from './EmptyTable';

/**
 * A drawing, and the tests are about what it must never become.
 *
 * It sits on the sign-in sheet where a list of seated chairs sat for one build
 * and was removed for being read as the panel. The whole reason this can take
 * that place is that it says nothing — so the things worth asserting are all
 * absences.
 */

it('carries no words at all', async () => {
  // The moment it labels a seat it is a cast list again, which is what it
  // replaced. There is nothing here to read, in any language.
  await render(<EmptyTable seats={3} />);

  expect(screen.queryByText(/.+/)).toBeNull();
});

it('is not announced to a screen reader', async () => {
  // Decorative. The heading above it already says "Keep this room"; a device
  // that stands for the room would only make somebody hear it described twice,
  // and there is no information in it that the copy does not carry.
  await render(<EmptyTable seats={3} />);

  expect(screen.queryByLabelText(/.+/)).toBeNull();
  expect(screen.queryByRole('image')).toBeNull();
});

it('draws a chair for every seat the tier allows', async () => {
  await render(<EmptyTable seats={5} />);

  // `includeHiddenElements`, because the drawing is hidden from the
  // accessibility tree on purpose and the default query honours that. Needing
  // the flag here is the proof that the test above is not passing by accident.
  expect(screen.queryAllByTestId('chair-mark', { includeHiddenElements: true }))
    .toHaveLength(5);
});

it('draws no chairs at all rather than one, when there is no table', async () => {
  // A rail with a single bead on it is not a table, it is a pin. If a tier
  // ever seats nobody the drawing should be absent, not degenerate.
  await render(<EmptyTable seats={0} />);

  expect(screen.queryAllByTestId('chair-mark', { includeHiddenElements: true }))
    .toHaveLength(0);
});
