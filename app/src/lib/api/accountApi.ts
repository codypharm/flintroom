import { SignedOut } from '../auth/session';

/**
 * The account endpoint, over HTTP.
 *
 * One method today, and its own module rather than a third method on
 * `authApi`: that one exists to obtain and spend credentials and is called
 * *by* the session layer, while this one is called by a screen and needs a
 * bearer token the session layer hands out. Folding them together would make
 * `AuthApi` depend on the thing that depends on it.
 *
 * Written by hand for the reason `authApi` gives: `openapi-fetch` returns
 * `{ data, error }` and never throws, and the status-to-error mapping below is
 * the substance of this file. `schema.d.ts` still types the payload.
 */

export interface AccountApiOptions {
  baseUrl: string;
  /** The session's, so this never touches storage or refresh logic itself. */
  accessToken(): Promise<string>;
  /** Injected so tests need no network. Defaults to the platform's. */
  fetch?: typeof fetch;
}

export interface AccountApi {
  /** Schedules deletion and returns when the purge happens. */
  deleteAccount(): Promise<Date>;
}

/** What the contract calls a scheduled deletion, before the app renames it. */
interface DeletionScheduledBody {
  purge_at: string;
}

export function createAccountApi({
  baseUrl,
  accessToken,
  fetch: fetcher = fetch,
}: AccountApiOptions): AccountApi {
  return {
    deleteAccount: async () => {
      const response = await fetcher(`${baseUrl}/v1/me`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${await accessToken()}` },
      });

      // Separated from every other failure, exactly as `authApi` separates it.
      // A caller that read a 401 as "the request failed" would tell somebody
      // their account was untouched, when what happened is that they are not
      // signed in and the account's state is unknown to them.
      if (response.status === 401) {
        throw new SignedOut('refused by DELETE /v1/me');
      }

      if (!response.ok) {
        throw new Error(`DELETE /v1/me failed with ${response.status}`);
      }

      const body = (await response.json()) as DeletionScheduledBody;

      // The server's date, never a window computed here. The client's copy of
      // "seven days" would drift the moment the server's changed, and this is
      // the date somebody plans around.
      return new Date(body.purge_at);
    },
  };
}
