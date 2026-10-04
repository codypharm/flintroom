import { useEffect, useRef } from 'react';
import { AppState } from 'react-native';

/**
 * Run `again` each time the app comes back to the foreground.
 *
 * For re-reading the balance. Focus covers moving between screens and misses
 * the case that matters for money: a purchase Apple finishes while the person
 * is somewhere else, or a webhook landing after the Minutes screen stopped
 * asking. Both leave a stale figure on a screen that never lost focus.
 *
 * Only on arrival at `active`. Leaving is not news, and reading on the way out
 * spends a request on a screen nobody is looking at.
 */
export function useOnReturn(again: () => void): void {
  // The latest callback without re-subscribing on every render.
  // Written in an effect rather than during render, which the React Compiler
  // would refuse.
  const latest = useRef(again);
  useEffect(() => {
    latest.current = again;
  }, [again]);

  useEffect(() => {
    const listening = AppState.addEventListener('change', (state) => {
      if (state === 'active') latest.current();
    });
    return () => listening.remove();
  }, []);
}
