import { createContext, useCallback, useContext, useEffect, useState } from 'react';

import { createMeApi } from '../api/meApi';
import { API_BASE_URL, auth } from './index';
import { whoIsThere, type WhoIsThere } from './gate';

/**
 * Who is at the door, held for the whole app.
 *
 * The gate has to be asked once at launch and re-asked at exactly two moments —
 * somebody signs in, and somebody describes their room — so the answer cannot
 * live inside the screen that draws it. A context is the smallest thing that
 * lets the two screens which *change* the answer tell the layout that decides
 * on it.
 *
 * `checking` is a fourth state that never reaches `whoIsThere`, because it is
 * not a conclusion — it is the absence of one. Kept apart so the layout cannot
 * accidentally treat "we have not asked yet" as "no credential", which would
 * flash the sign-in screen at every signed-in launch.
 */

const me = createMeApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

export type AtTheDoor = WhoIsThere | 'checking';

interface Gateway {
  who: AtTheDoor;
  /** Ask again. Called after signing in, and after the survey lands. */
  recheck: () => void;
}

const Context = createContext<Gateway>({ who: 'checking', recheck: () => undefined });

export function useGateway(): Gateway {
  return useContext(Context);
}

export function Gateway({ children }: { children: React.ReactNode }) {
  const [who, setWho] = useState<AtTheDoor>('checking');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;

    void whoIsThere(() => me.read()).then((seen) => {
      if (live) setWho(seen);
    });

    return () => {
      live = false;
    };
  }, [attempt]);

  const recheck = useCallback(() => {
    // Back to `checking` first, so the layout draws the splash rather than
    // holding a stale answer while the new one is in flight. Somebody who has
    // just signed in would otherwise see the sign-in screen for another beat.
    setWho('checking');
    setAttempt((made) => made + 1);
  }, []);

  return <Context.Provider value={{ who, recheck }}>{children}</Context.Provider>;
}
