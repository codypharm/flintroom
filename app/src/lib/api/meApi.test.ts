import { SignedOut } from '../auth/session';
import { createMeApi } from './meApi';

/**
 * The two questions a launch has to answer before it can draw anything.
 *
 * `GET /v1/me` has existed since auth was built and its docstring has always
 * said "the mobile client calls this on launch. A 200 means go straight in; a
 * 401 means sign in again." Nothing called it. #86 is what that cost: an app
 * that draws itself fully for somebody with no account and explains nothing.
 */

function api(reply: Partial<Response> & { json?: () => Promise<unknown> }) {
  const fetcher = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ user_id: 'u-1', onboarded: true }),
    ...reply,
  });

  return {
    fetcher,
    me: createMeApi({
      baseUrl: 'https://flintroom.test',
      accessToken: async () => 'a-token',
      fetch: fetcher as unknown as typeof fetch,
    }),
  };
}

it('says who is signed in, and whether they have described a room', async () => {
  // Two questions in one round trip, on the slowest screen in the product.
  const { fetcher, me } = api({});

  expect(await me.read()).toEqual({ userId: 'u-1', onboarded: true });
  expect(fetcher.mock.calls[0][0]).toBe('https://flintroom.test/v1/me');
});

it('reports a credential that is no longer good as signed out', async () => {
  // The whole point of the gate. This is the one refusal that has a screen.
  const { me } = api({ ok: false, status: 401 });

  await expect(me.read()).rejects.toBeInstanceOf(SignedOut);
});

it('does not report an unreachable server as being signed out', async () => {
  // The failure that would be worst to get wrong: treating a flaky connection
  // as a dead credential signs somebody out of an account that is perfectly
  // fine, and on a phone that is most of the time.
  const { me } = api({ ok: false, status: 502 });

  const failed = await me.read().catch((error) => error);

  expect(failed).toBeInstanceOf(Error);
  expect(failed).not.toBeInstanceOf(SignedOut);
});

it('sends the plan in the wire’s own casing', async () => {
  // `happens_on`, not `happensOn`. Every field is optional on the server, so a
  // silent mismatch drops the date without failing anything — the same trap
  // `authApi` records for the sign-in path.
  const { fetcher, me } = api({ status: 204, json: async () => ({}) });

  await me.describeTheRoom({
    situation: 'board_review',
    happensOn: '2026-09-01',
    role: 'exec',
    audience: ['budget', 'rival'],
  });

  const [url, init] = fetcher.mock.calls[0];
  expect(url).toBe('https://flintroom.test/v1/onboarding');
  expect(JSON.parse(init.body)).toEqual({
    situation: 'board_review',
    happens_on: '2026-09-01',
    role: 'exec',
    audience: ['budget', 'rival'],
  });
});
