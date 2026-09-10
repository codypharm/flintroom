import { boundedFetch } from '../net/bounded';

/**
 * First-party analytics — the app's half of #105.
 *
 * `track` fires and forgets, and forgetting is the contract: telemetry must
 * never be something a screen waits on, throws over, or signs anybody out
 * for. A lost event is a lost event — the questions this data answers are
 * curves, and a curve does not care about one dropped point. That is also
 * why this client, alone among them, does not throw `SignedOut` on a 401:
 * the others speak for things a person asked for; this one speaks for
 * nothing they can see.
 *
 * What may be tracked is a *name* — `app_open`, `settings.viewed` — and
 * nothing else. No properties travel, because the server refuses anything
 * shaped like prose and the table deliberately has nowhere to put it. The
 * funnel facts live in the domain tables already; the one thing only this
 * side can report is that the app was opened at all.
 */

export interface AnalyticsOptions {
  baseUrl: string;
  accessToken(): Promise<string>;
  fetch?: typeof fetch;
}

export interface Analytics {
  /** Report that a moment happened. Returns immediately, never throws. */
  track(name: string): void;
}

export function createAnalytics({
  baseUrl,
  accessToken,
  fetch: fetcher = boundedFetch(),
}: AnalyticsOptions): Analytics {
  return {
    track(name) {
      void (async () => {
        await fetcher(`${baseUrl}/v1/events`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${await accessToken()}`,
          },
          body: JSON.stringify({ events: [{ name }] }),
        });
      })().catch(() => undefined);
    },
  };
}
