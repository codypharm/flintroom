import { SignedOut } from '../auth/session';

/**
 * How much time in the room this account has left.
 *
 * **Two fields, and the omissions are the product rule.** `Product.md` §4.6
 * forbids a depleting counter — "2 of 5 credits left" — so the server publishes
 * whole minutes and a boolean and no seconds at all. A client that received
 * seconds would be one rounding decision away from promising a minute that is
 * not there, and one layout decision away from drawing the counter.
 *
 * There is no breakdown by bucket either. Which bucket a second is spent from
 * is an internal ordering rule, and three numbers depleting in turn is exactly
 * the credits display that rule exists to refuse.
 */

export interface Held {
  /** Whole minutes of interrogation available. Never a fraction, never seconds. */
  minutes: number;
  /**
   * Whether there is any time at all.
   *
   * Published separately rather than derived from `minutes > 0`, because the
   * server decides it: a room may open on a balance the client would round to
   * zero, and the boolean is what a screen should gate on.
   */
  any: boolean;
}

export interface BalanceApi {
  read(): Promise<Held>;
}

export interface BalanceApiOptions {
  baseUrl: string;
  accessToken(): Promise<string>;
  fetch?: typeof fetch;
}

export function createBalanceApi({
  baseUrl,
  accessToken,
  fetch: fetcher = fetch,
}: BalanceApiOptions): BalanceApi {
  return {
    read: async () => {
      const response = await fetcher(`${baseUrl}/v1/balance`, {
        headers: { Authorization: `Bearer ${await accessToken()}` },
      });

      if (response.status === 401) {
        throw new SignedOut('refused by /v1/balance');
      }
      if (!response.ok) {
        throw new Error(`/v1/balance failed with ${response.status}`);
      }

      const body = (await response.json()) as {
        remaining_minutes: number;
        has_time_remaining: boolean;
      };

      return { minutes: body.remaining_minutes, any: body.has_time_remaining };
    },
  };
}
