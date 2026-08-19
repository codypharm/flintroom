import { SignedOut } from '../auth/session';
import { createAccountApi } from './accountApi';

/**
 * `DELETE /v1/me`, over HTTP.
 *
 * Thin, like `authApi` beside it, and translating the same two things: the
 * wire's spelling into the app's, and a status into something a caller can act
 * on. What is different is that this endpoint takes a bearer token — the
 * account being destroyed is entirely determined by the credential, and there
 * is no body and no path parameter a caller could point somewhere else.
 */
function apiReturning(status: number, body: unknown) {
  const calls: { url: string; method?: string; headers?: Record<string, string> }[] = [];

  const fetcher = async (url: string, init: RequestInit) => {
    calls.push({
      url,
      method: init.method,
      headers: init.headers as Record<string, string>,
    });

    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    } as Response;
  };

  return {
    api: createAccountApi({
      baseUrl: 'https://api.example',
      fetch: fetcher as typeof fetch,
      accessToken: async () => 'access-1',
    }),
    calls,
  };
}

it('sends a DELETE with the caller’s bearer token', async () => {
  const { api, calls } = apiReturning(202, { purge_at: '2026-08-25T09:00:00Z' });

  await api.deleteAccount();

  expect(calls).toEqual([
    {
      url: 'https://api.example/v1/me',
      method: 'DELETE',
      headers: { Authorization: 'Bearer access-1' },
    },
  ]);
});

it('returns when the purge happens, as a Date', async () => {
  // The app tells the person a date, and it must be the server's rather than
  // one computed here from a window the client believes in. A client-side
  // seven days would drift the moment the server's changed, and the sentence
  // it produces is the one the person plans around.
  const { api } = apiReturning(202, { purge_at: '2026-08-25T09:00:00Z' });

  await expect(api.deleteAccount()).resolves.toEqual(
    new Date('2026-08-25T09:00:00Z')
  );
});

it('reports a 401 as the session being over, not as a failed deletion', async () => {
  // The same distinction `authApi` makes, and it matters more here: a caller
  // that read this as "the request failed" would tell somebody their account
  // was untouched when what actually happened is that they are not signed in.
  const { api } = apiReturning(401, {});

  await expect(api.deleteAccount()).rejects.toBeInstanceOf(SignedOut);
});

it('rejects on anything else rather than pretending it worked', async () => {
  const { api } = apiReturning(503, {});

  await expect(api.deleteAccount()).rejects.toThrow('503');
});

it('reads the account own recording window, rather than assuming a tier', async () => {
  // The disclosure sheet states this number out loud. It is per tier and moves
  // when somebody upgrades, so a hardcoded thirty would eventually be a
  // disclosure that misinforms — which is the one kind of bug in this flow that
  // is not merely a bug.
  const fetcher = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ retention_days: 90 }),
  });

  const account = createAccountApi({
    baseUrl: 'https://flintroom.test',
    accessToken: async () => 'a-token',
    fetch: fetcher as unknown as typeof fetch,
  });

  await expect(account.recordingWindow()).resolves.toBe(90);
  expect(fetcher.mock.calls[0][0]).toBe('https://flintroom.test/v1/preferences/recording');
});
