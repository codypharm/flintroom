import type { OnboardingPlan } from '../auth/session';
import { SignedOut } from '../auth/session';
import { boundedFetch } from '../net/bounded';

/**
 * Who is signed in, and whether they have told us anything yet.
 *
 * Its own client rather than a method on `authApi`, because `authApi` is the
 * unauthenticated half — it exchanges provider tokens for ours and holds no
 * credential of its own. Everything here needs one.
 */

export interface WhoTheyAre {
  userId: string;
  /**
   * Whether this account has ever described a room it is preparing for.
   *
   * Keyed to the account rather than the install, which is the whole reason it
   * comes from the server: a reinstall is the moment a returning user most
   * needs to be left alone, and a local flag is exactly what a reinstall
   * destroys.
   */
  onboarded: boolean;
}

export interface MeApi {
  /** Raises `SignedOut` when the credential is no longer good. */
  read(): Promise<WhoTheyAre>;
  /** Say what you are preparing for, after signing in rather than before. */
  describeTheRoom(plan: OnboardingPlan): Promise<void>;
}

export interface MeApiOptions {
  baseUrl: string;
  accessToken(): Promise<string>;
  fetch?: typeof fetch;
}

export function createMeApi({
  baseUrl,
  accessToken,
  fetch: fetcher = boundedFetch(),
}: MeApiOptions): MeApi {
  const send = async (path: string, init: RequestInit = {}): Promise<Response> => {
    const response = await fetcher(`${baseUrl}${path}`, {
      ...init,
      headers: {
        ...(init.body === undefined ? {} : { 'content-type': 'application/json' }),
        Authorization: `Bearer ${await accessToken()}`,
      },
    });

    // Only a 401 is a signed-out session, and the distinction is the most
    // important one this file makes. Treating an unreachable server as a dead
    // credential signs somebody out of a perfectly good account — and on a
    // phone, unreachable is most of the time.
    if (response.status === 401) {
      throw new SignedOut(`refused by ${path}`);
    }
    if (!response.ok) {
      throw new Error(`${path} failed with ${response.status}`);
    }

    return response;
  };

  return {
    read: async () => {
      const body = (await (await send('/v1/me')).json()) as {
        user_id: string;
        onboarded?: boolean;
      };

      return { userId: body.user_id, onboarded: body.onboarded ?? false };
    },

    describeTheRoom: async (plan) => {
      await send('/v1/onboarding', {
        method: 'POST',
        // The server's spelling, not the app's. Every field is optional there,
        // so a mismatch drops the value without failing anything.
        body: JSON.stringify({
          situation: plan.situation,
          happens_on: plan.happensOn,
          role: plan.role,
          audience: plan.audience,
        }),
      });
    },
  };
}
