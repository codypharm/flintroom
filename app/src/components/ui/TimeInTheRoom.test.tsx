import { render, screen } from '@testing-library/react-native';

import { TimeInTheRoom } from './TimeInTheRoom';

it('says the minutes plainly, in the plural', async () => {
  await render(<TimeInTheRoom minutes={55} any />);

  expect(screen.getByLabelText('You have 55 minutes')).toBeTruthy();
});

it('holds one minute without calling it minutes', async () => {
  // Seen on a phone during a device run: "You have 1 minutes". The chip is on
  // every top-level screen, and the account most likely to be reading it
  // closely is exactly the one down to its last minute.
  await render(<TimeInTheRoom minutes={1} any />);

  expect(screen.getByLabelText('You have 1 minute')).toBeTruthy();
  expect(screen.queryByText(/minutes/)).toBeNull();
});

it('says there are none rather than counting to zero', async () => {
  await render(<TimeInTheRoom minutes={0} any={false} />);

  expect(screen.getByLabelText('No minutes right now')).toBeTruthy();
});
