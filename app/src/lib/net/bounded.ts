/**
 * A deadline on every request, because a request without one can hang forever.
 *
 * Measured on an emulator with the network removed, 2026-09-10: the Library
 * spun for eight minutes and said nothing. Its failure branch was written and
 * correct and simply never ran, because the fetch never settled. A network
 * that *refuses* traffic produces a rejection; one that silently drops it
 * produces nothing at all, and dropping is what a captive portal, a dead cell
 * edge, and a switched-off radio all do. React Native's `fetch` imposes no
 * timeout of its own, so nothing anywhere turned that silence into an event.
 *
 * This is what makes every connectivity sentence in the app reachable.
 * `isOffline` can explain a failure; it cannot invent one.
 *
 * **Generous on purpose.** These ceilings exist to catch a socket that is
 * never going to answer, not to hurry a slow one. A coaching turn waits on a
 * model, and a deck upload is megabytes over whatever connection the user has
 * — cutting either short to feel responsive would break working features to
 * improve a broken one.
 */

/** Ordinary JSON calls: slow is fine, silent is not. */
export const REQUEST_TIMEOUT_MS = 30_000;

/**
 * A deck on its way to object storage, bounded minutes rather than seconds
 * away from the ordinary case. The upload is a single presigned PUT through
 * the same injectable fetcher (`materialsApi`), so without its own ceiling it
 * would inherit one sized for a JSON round trip and fail every large deck on
 * a hotel connection.
 */
export const UPLOAD_TIMEOUT_MS = 120_000;

/**
 * The same `fetch`, with a deadline attached.
 *
 * A caller that brought its own `signal` keeps it untouched. The room and the
 * reconnect loop manage their own lifetimes, and a deadline imposed on top of
 * theirs is how a working stream dies at thirty seconds for no reason anybody
 * can trace.
 */
export function boundedFetch(
  ms: number = REQUEST_TIMEOUT_MS,
  underlying: typeof fetch = fetch
): typeof fetch {
  return async (input, init) => {
    if (init?.signal) {
      return underlying(input, init);
    }

    const deadline = new AbortController();
    const timer = setTimeout(() => deadline.abort(), ms);

    try {
      return await underlying(input, { ...init, signal: deadline.signal });
    } finally {
      // In `finally`, so a response that arrives with a second to spare does
      // not leave a timer holding a reference to an aborted controller — and,
      // on a screen that fires many small reads, does not leave dozens.
      clearTimeout(timer);
    }
  };
}
