import { renderHook } from '@testing-library/react-native';
import { AppState, type AppStateStatus } from 'react-native';

import { useOnReturn } from './foreground';

/**
 * Reading the balance again when the app comes back.
 *
 * Focus is not enough on its own. A purchase that Apple finishes while the
 * person is in another app, or a webhook that lands after the Minutes screen
 * stopped asking, leaves the figure stale on a screen that never lost focus.
 * On 2026-10-02 the only way to see a sandbox top-up was to kill the app.
 */

let heard: ((state: AppStateStatus) => void) | undefined;
const remove = jest.fn();

beforeEach(() => {
  heard = undefined;
  remove.mockClear();
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_, listener) => {
    heard = listener as (state: AppStateStatus) => void;
    return { remove };
  });
});

it('runs when the app returns to the foreground', async () => {
  const again = jest.fn();
  await renderHook(() => useOnReturn(again));

  heard?.('background');
  heard?.('active');

  expect(again).toHaveBeenCalledTimes(1);
});

it('does not run on the way out', async () => {
  const again = jest.fn();
  await renderHook(() => useOnReturn(again));

  heard?.('inactive');
  heard?.('background');

  expect(again).not.toHaveBeenCalled();
});

it('stops listening when the screen goes', async () => {
  const { unmount } = await renderHook(() => useOnReturn(jest.fn()));

  await unmount();

  expect(remove).toHaveBeenCalled();
});
