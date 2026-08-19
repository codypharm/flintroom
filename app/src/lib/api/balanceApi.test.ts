import { SignedOut } from '../auth/session';
import { createBalanceApi } from './balanceApi';

/**
 * How much time in the room this account has left.
 *
 * The endpoint has existed since the ledger was built and nothing has ever
 * called it. `SettingsScreen` shows a figure, and it has been a hardcoded
 * `minutesRemaining: 15` since it was written — a screen telling somebody a
 * number about their own money that came from a constant.
 */

function api(reply: Partial<Response> & { json?: () => Promise<unknown> }) {
  const fetcher = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ remaining_minutes: 118, has_time_remaining: true }),
    ...reply,
  });

  return {
    fetcher,
    balance: createBalanceApi({
      baseUrl: 'https://flintroom.test',
      accessToken: async () => 'a-token',
      fetch: fetcher as unknown as typeof fetch,
    }),
  };
}

it('reads whole minutes, and whether there are any', async () => {
  // Two fields and no seconds, which is the server refusing to let a client
  // invent §4.6's forbidden counter: raw seconds on the wire is that counter
  // with the rounding left to whoever wrote the app, and one of them rounds up
  // and promises a minute that is not there.
  const { fetcher, balance } = api({});

  const held = await balance.read();

  expect(fetcher.mock.calls[0][0]).toBe('https://flintroom.test/v1/balance');
  expect(held).toEqual({ minutes: 118, any: true });
});

it('reports an account with nothing left, without pretending otherwise', async () => {
  // Zero is a real answer and the screen has something specific to say about
  // it. Rounding it away, or treating it as a failure to load, is how somebody
  // taps Start and gets a refusal they were given no warning of.
  const { balance } = api({
    json: async () => ({ remaining_minutes: 0, has_time_remaining: false }),
  });

  await expect(balance.read()).resolves.toEqual({ minutes: 0, any: false });
});

it('reports a signed-out session as such rather than as an empty balance', async () => {
  const { balance } = api({ ok: false, status: 401 });

  await expect(balance.read()).rejects.toBeInstanceOf(SignedOut);
});
