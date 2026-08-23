/**
 * The way back into a dropped room — docs/reconnect.md, the client's half.
 *
 * The server holds a dropped room open for thirty seconds; this loop is what
 * spends that window trying to get back in. Each attempt re-mints a stream
 * ticket and rejoins the same socket route, and the three answers an attempt
 * can give are the whole protocol:
 *
 * - `joined` — the presenter is back in the same room, mid-conversation.
 * - `gone` — the server said there is no live room to rejoin. This is not
 *   only failure: once the reaper settles the room (30–45 seconds after the
 *   drop), the re-mint refuses with exactly this, so `gone` doubles as "the
 *   room is settled and the debrief is ready". That is why the loop keeps
 *   asking past the server's own window instead of matching it — the refusal
 *   is the one race-free signal that it is time to navigate.
 * - `retry` — the network is still down, or the request died. Wait and ask
 *   again.
 *
 * The outer bound exists only for a server that never answers at all; the
 * ordinary exit is `gone` or `joined`. A function rather than logic in the
 * interrogation screen, for `closing.ts`'s reason: a loop that only exists
 * inside a `useCallback` cannot be tested, and this one decides how long a
 * presenter stares at "getting you back in".
 */

export type Attempt = 'joined' | 'retry' | 'gone';

export interface Reconnecting {
  /** One try: re-mint a ticket and rejoin. */
  attempt: () => Promise<Attempt>;
  /**
   * How long to keep trying before giving up on an answer either way.
   *
   * Comfortably past the server's 30-second window plus one reaper sweep, so
   * the ordinary give-up is the server's refusal rather than this clock.
   */
  windowMs?: number;
  /** The pause between attempts, so a recovering network is not hammered. */
  delayMs?: number;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
}

const WINDOW_MS = 60_000;
const DELAY_MS = 2_000;

const pause = (ms: number) =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });

export async function reconnectRoom({
  attempt,
  windowMs = WINDOW_MS,
  delayMs = DELAY_MS,
  sleep = pause,
  now = Date.now,
}: Reconnecting): Promise<'joined' | 'gone'> {
  const deadline = now() + windowMs;

  while (now() < deadline) {
    let answer: Attempt;
    try {
      answer = await attempt();
    } catch {
      // A request that died is the network still being the problem this loop
      // exists for — one more transient failure, not a verdict.
      answer = 'retry';
    }

    if (answer !== 'retry') {
      return answer;
    }
    await sleep(delayMs);
  }

  return 'gone';
}
