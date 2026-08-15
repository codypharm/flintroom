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
