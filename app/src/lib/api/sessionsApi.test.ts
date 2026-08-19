import { SignedOut } from '../auth/session';
import { createSessionsApi } from './sessionsApi';

/**
 * The two calls that open and close a metered room.
 *
 * Everything else about a session travels on the socket. These are the door
 * and the way out, and the reason they are a client rather than two `fetch`
 * calls in a screen is that the screen has a microphone open while they run.
 */

function api(reply: Partial<Response> & { json?: () => Promise<unknown> }) {
  const fetcher = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({}),
    ...reply,
  });

  return {
    fetcher,
    sessions: createSessionsApi({
      baseUrl: 'https://flintroom.test',
      accessToken: async () => 'a-token',
      fetch: fetcher as unknown as typeof fetch,
    }),
  };
}

const STARTED = {
  id: 'session-1',
  stream_ticket: 'one-use',
  archetypes: ['cfo', 'champion'],
};

it('starts a room grounded in exactly what the presenter chose', async () => {
  // Setup holds the seating in local state — nothing persists it — so a room
  // started from whatever the server last saved would seat a panel the person
  // in front of it did not assemble.
  const { fetcher, sessions } = api({ status: 201, json: async () => STARTED });

  await sessions.start({ archetypes: ['cfo', 'champion'], materialIds: ['m-1'] });

  const [url, init] = fetcher.mock.calls[0];
  expect(url).toBe('https://flintroom.test/v1/sessions');
  expect(init.method).toBe('POST');
  expect(JSON.parse(init.body)).toEqual({
    archetypes: ['cfo', 'champion'],
    material_ids: ['m-1'],
  });
});

it('hands back the ticket and the room it opens, together', async () => {
  // The ticket is single-use and lives for seconds. Returning it separately
  // from the session it belongs to is how one gets spent on the wrong room.
  const { sessions } = api({ status: 201, json: async () => STARTED });

  const room = await sessions.start({ archetypes: [], materialIds: [] });

  expect(room).toEqual({
    id: 'session-1',
    streamTicket: 'one-use',
    archetypes: ['cfo', 'champion'],
  });
});

it('ends a room as an intent, without naming its own reason', async () => {
  // `user_ended` is the only ending a client is in a position to report, and
  // the server does not read one from the body — every other reason in the
  // enum decides whether minutes come back, so a client that could name one
  // would be choosing its own refund.
  const { fetcher, sessions } = api({});

  await sessions.end('session-1');

  const [url, init] = fetcher.mock.calls[0];
  expect(url).toBe('https://flintroom.test/v1/sessions/session-1/end');
  expect(init.method).toBe('POST');
  expect(init.body).toBeUndefined();
});

it('treats a session already settled as ended, not as a failure', async () => {
  // The socket closing and the End button race by design: the room can settle
  // underneath this call. Both outcomes are the same to the presenter, who is
  // already on their way to the debrief.
  const { sessions } = api({ ok: false, status: 409 });

  await expect(sessions.end('session-1')).resolves.toBeUndefined();
});

it('reports a signed-out session as such, rather than as a dead room', async () => {
  const { sessions } = api({ ok: false, status: 401 });

  await expect(sessions.start({ archetypes: [], materialIds: [] })).rejects.toBeInstanceOf(
    SignedOut
  );
});
