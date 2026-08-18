import { SignedOut, type AuthApi, type IssuedTokens } from '../auth/session';

/**
 * The auth endpoints, over HTTP.
 *
 * Thin on purpose. Every decision about *when* to refresh, what to keep and
 * what to throw away lives in `session.ts`; this only translates. Two things
 * are translated: the wire's snake_case into the app's camelCase, and an HTTP
 * status into the distinction `session.ts` acts on.
 */

/**
 * Written by hand rather than through the generated client.
 *
 * `openapi-fetch` returns `{ data, error }` and never throws, which is a fine
 * shape for a screen and the wrong one here — `AuthApi` is defined in terms of
 * rejections, and the status-to-error mapping below is the whole substance of
 * this file. Wrapping a non-throwing client in a throwing one would add a
 * layer that only unwraps what it just wrapped. The generated `schema.d.ts`
 * still types the payloads.
 */
export interface AuthApiOptions {
  baseUrl: string;
  /** Injected so tests need no network. Defaults to the platform's. */
  fetch?: typeof fetch;
}

/** What the contract calls a signed-in pair, before the app renames it. */
interface SignedInBody {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  /** Absent from a refresh, and defaulted below rather than assumed. */
  deletion_cancelled?: boolean;
}

export function createAuthApi({
  baseUrl,
  fetch: fetcher = fetch,
}: AuthApiOptions): AuthApi {
  const post = async (path: string, body: unknown): Promise<Response> => {
    const response = await fetcher(`${baseUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (response.ok) {
      return response;
    }

    // 401 is the only status that means the session is over. The server
    // answers it identically for expired, revoked and replayed — so that a
    // caller holding a token it should not have learns nothing by presenting
    // it — and all three are unrecoverable here.
    //
    // Everything else is a failure to reach a working server, and must not be
    // mistaken for one: reported as SignedOut, a minute of downtime would
    // clear every user's credentials at once.
    if (response.status === 401) {
      throw new SignedOut(`refused by ${path}`);
    }

    throw new Error(`POST ${path} failed with ${response.status}`);
  };

  const issued = async (
    response: Response,
    { admitting = false }: { admitting?: boolean } = {}
  ): Promise<IssuedTokens> => {
    const body = (await response.json()) as SignedInBody;

    return {
      accessToken: body.access_token,
      refreshToken: body.refresh_token,
      expiresIn: body.expires_in,
      // Only a sign-in may report this. Rotating a token is not somebody
      // coming back, so a refresh that carried a cancellation would announce
      // an event that did not happen — on a path that runs unattended, minutes
      // after the sign-in that did. Read from the flag rather than from the
      // body's shape, so a server that starts sending the field on refresh
      // cannot change what the app says.
      deletionCancelled: admitting && body.deletion_cancelled === true,
    };
  };

  return {
    signIn: async (provider, idToken, plan) =>
      issued(
        await post('/v1/auth/sessions', {
          provider,
          id_token: idToken,
          // Spread rather than set, so an ordinary launch sends no key at all.
          // An empty object would be read by the server as answers and would
          // blank the plan somebody built on their first run.
          ...(plan
            ? {
                onboarding: {
                  situation: plan.situation,
                  // The wire's own casing, translated here and nowhere else.
                  // A silent mismatch would drop the date without failing
                  // anything, since every field on `Answers` is optional.
                  happens_on: plan.happensOn,
                  role: plan.role,
                  audience: plan.audience,
                },
              }
            : {}),
        }),
        { admitting: true }
      ),

    refresh: async (refreshToken) =>
      issued(await post('/v1/auth/sessions/refresh', { refresh_token: refreshToken })),

    signOut: async (refreshToken) => {
      await post('/v1/auth/sessions/sign-out', { refresh_token: refreshToken });
    },
  };
}
