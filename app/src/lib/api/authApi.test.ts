import { SignedOut } from '../auth/session';
import { createAuthApi } from './authApi';

/**
 * The auth endpoints, over HTTP.
 *
 * Thin by design — the interesting decisions are in `session.ts`, which this
 * feeds. What lives here is the translation nobody else should have to know
 * about: snake_case on the wire, camelCase in the app, and which HTTP status
 * means the session is unrecoverable.
 *
 * That last one carries weight. A 401 from refresh means the family is revoked
 * and the user must sign in again; anything else means try later. Confusing
 * them either strands a user on a sign-in screen for a flaky connection, or
 * retries a dead token forever.
 */
function apiReturning(
  status: number,
  body: unknown
): { api: ReturnType<typeof createAuthApi>; calls: { url: string; body: unknown }[] } {
  const calls: { url: string; body: unknown }[] = [];

  const fetcher = async (url: string, init: { body?: string }) => {
    calls.push({ url, body: init.body ? JSON.parse(init.body) : undefined });

    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    } as Response;
  };

  return {
    api: createAuthApi({ baseUrl: 'https://api.example', fetch: fetcher as typeof fetch }),
    calls,
  };
}

const issued = {
  access_token: 'access-1',
  refresh_token: 'refresh-1',
  token_type: 'bearer',
  expires_in: 900,
};

describe('signing in', () => {
  it('posts the provider token and returns the pair in the app’s shape', async () => {
    const { api, calls } = apiReturning(200, issued);

    await expect(api.signIn('apple', 'apple-id-token')).resolves.toEqual({
      accessToken: 'access-1',
      refreshToken: 'refresh-1',
      expiresIn: 900,
      // Always present, never optional. A caller reading an absent field as
      // "nothing happened" and one reading it as "unknown" would both be
      // guessing, on the one signal that decides whether the user is told
      // their deletion was reversed.
      deletionCancelled: false,
    });

    expect(calls).toEqual([
      {
        url: 'https://api.example/v1/auth/sessions',
        // snake_case on the wire, which is the contract's spelling and not
        // the app's. This is the one place the two meet.
        body: { provider: 'apple', id_token: 'apple-id-token' },
      },
    ]);
  });
});

describe('refreshing', () => {
  it('trades the refresh token for a fresh pair', async () => {
    const { api, calls } = apiReturning(200, issued);

    await api.refresh('refresh-old');

    expect(calls[0]).toEqual({
      url: 'https://api.example/v1/auth/sessions/refresh',
      body: { refresh_token: 'refresh-old' },
    });
  });

  it('reports a 401 as being signed out, which cannot be retried', async () => {
    // The server answers 401 for every refusal — expired, revoked, or replayed
    // — deliberately, so a caller holding a token it should not have learns
    // nothing by presenting it. All of them mean the same thing here.
    const { api } = apiReturning(401, { code: 'not_authenticated' });

    await expect(api.refresh('refresh-old')).rejects.toBeInstanceOf(SignedOut);
  });

  it('does not report a server fault as being signed out', async () => {
    // A 502 is our outage, not the user's session ending. Reported as
    // SignedOut it would clear the credentials — turning a minute of downtime
    // into every user having to sign in again, with no way back for anyone
    // whose provider account had since changed.
    const { api } = apiReturning(502, { code: 'provider_unavailable' });

    await expect(api.refresh('refresh-old')).rejects.not.toBeInstanceOf(SignedOut);
  });
});

describe('a sign-in that reverses a deletion', () => {
  it('carries the fact through rather than dropping it at the boundary', async () => {
    // `docs/account-deletion.md` decision 5 makes signing in *do* something —
    // it calls off a scheduled deletion — and the message is the load-bearing
    // half of that decision. An account that quietly un-deletes itself is
    // worse than one that stayed deleted, because the user never learns their
    // data is still there.
    //
    // This layer cannot say the sentence and should not know it. What it must
    // not do is discard the only signal that the sentence is owed, which is
    // exactly the kind of loss a translation layer makes silently.
    const { api } = apiReturning(200, { ...issued, deletion_cancelled: true });

    await expect(api.signIn('google', 'google-id-token')).resolves.toMatchObject({
      deletionCancelled: true,
    });
  });

  it('is false on the ordinary sign-in, which is almost all of them', async () => {
    const { api } = apiReturning(200, issued);

    await expect(api.signIn('google', 'google-id-token')).resolves.toMatchObject({
      deletionCancelled: false,
    });
  });

  it('is never claimed by a refresh', async () => {
    // Rotating a token is not somebody coming back, so a refresh reporting a
    // cancellation would be announcing an event that did not happen — on a
    // path that runs unattended, minutes after the sign-in that did.
    const { api } = apiReturning(200, { ...issued, deletion_cancelled: true });

    await expect(api.refresh('refresh-1')).resolves.toMatchObject({
      deletionCancelled: false,
    });
  });
});
