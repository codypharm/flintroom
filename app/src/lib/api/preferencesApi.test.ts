import { SignedOut } from '../auth/session';
import { createPreferencesApi } from './preferencesApi';

/**
 * Whether rooms are saved, and for how long.
 *
 * Both endpoints have existed since #52 and nothing has ever called them. The
 * switch on Settings raised an Alert saying "Not yet connected" — which was at
 * least honest — and the retention window beside it was a literal `30`, which
 * was not: it is per tier, and the free tier's number is only the right one
 * until somebody upgrades.
 */

function api(reply: Partial<Response> & { json?: () => Promise<unknown> } = {}) {
  const fetcher = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ records_rooms: true, retention_days: 30 }),
    ...reply,
  });

  return {
    fetcher,
    preferences: createPreferencesApi({
      baseUrl: 'https://flintroom.test',
      accessToken: async () => 'a-token',
      fetch: fetcher as unknown as typeof fetch,
    }),
  };
}

it('reads whether rooms are saved, and the window they are kept for', async () => {
  const { fetcher, preferences } = api();

  const held = await preferences.read();

  expect(fetcher.mock.calls[0][0]).toBe(
    'https://flintroom.test/v1/preferences/recording'
  );
  expect(held).toEqual({ recordsRooms: true, retentionDays: 30 });
});

it('carries the window back from the tier rather than assuming the free one', async () => {
  // The whole reason this is data. A pro account keeps rooms longer, and a
  // screen that stated 30 days to somebody on a longer window would be
  // understating what we hold — the one direction a retention disclosure must
  // never be wrong in.
  const { preferences } = api({
    json: async () => ({ records_rooms: true, retention_days: 90 }),
  });

  await expect(preferences.read()).resolves.toEqual({
    recordsRooms: true,
    retentionDays: 90,
  });
});

it('turns saving off with a PUT, and answers with what the server now holds', async () => {
  // The response is the truth, not the request. A client that echoed back what
  // it asked for would draw the switch in the position it was tapped into even
  // when the server settled somewhere else.
  const { fetcher, preferences } = api({
    json: async () => ({ records_rooms: false, retention_days: 30 }),
  });

  const now = await preferences.setRecordsRooms(false);

  const [url, init] = fetcher.mock.calls[0];
  expect(url).toBe('https://flintroom.test/v1/preferences/recording');
  expect(init.method).toBe('PUT');
  expect(JSON.parse(init.body)).toEqual({ records_rooms: false });
  expect(now).toEqual({ recordsRooms: false, retentionDays: 30 });
});

it('sends the credential on both calls', async () => {
  const { fetcher, preferences } = api();

  await preferences.read();
  await preferences.setRecordsRooms(true);

  for (const [, init] of fetcher.mock.calls) {
    expect(init.headers.Authorization).toBe('Bearer a-token');
  }
});

it('reports a signed-out session as such rather than as saving being off', async () => {
  // The distinction this file exists to keep. A 401 read as `recordsRooms:
  // false` would tell somebody their rooms are not being saved because their
  // token expired, which is both wrong and the reassuring direction to be
  // wrong in.
  const { preferences } = api({ ok: false, status: 401 });

  await expect(preferences.read()).rejects.toBeInstanceOf(SignedOut);
  await expect(preferences.setRecordsRooms(false)).rejects.toBeInstanceOf(SignedOut);
});

it('refuses to report a failed write as a successful one', async () => {
  const { preferences } = api({ ok: false, status: 502 });

  await expect(preferences.setRecordsRooms(false)).rejects.toThrow(/502/);
});
