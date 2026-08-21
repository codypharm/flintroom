import { createContext, useContext, type ReactNode } from 'react';

import type { Held } from '../api/balanceApi';

/**
 * The balance, read once and drawn wherever it appears.
 *
 * `(tabs)/_layout.tsx` already fetches it on focus for the app bar, and its
 * docstring gives the reason: four screens asking the same question disagree
 * for a beat whenever one of them is stale. Settings makes that worse rather
 * than merely wasteful — the bar and the "Time under fire" row are the same
 * number *on the same screen*, and two fetches is two chances for them to
 * differ in front of somebody.
 *
 * So the layout owns the read and this carries it down. Null means not read
 * yet, or read and failed; the difference does not matter to a reader and the
 * layout deliberately swallows the failure rather than drawing a refusal across
 * the app bar.
 */

const Balance = createContext<Held | null>(null);

export function HeldProvider({
  held,
  children,
}: {
  held: Held | null;
  children: ReactNode;
}) {
  return <Balance.Provider value={held}>{children}</Balance.Provider>;
}

/** What this account has left, or null while that is unknown. */
export function useHeld(): Held | null {
  return useContext(Balance);
}
