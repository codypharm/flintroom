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
  //
  // **422, and the status matters.** This asserted 409 and passed for the wrong
  // reason — `end` swallows every refusal, so any status would have. 409 on
  // this endpoint is not a thing the server does: `active_session_exists` is
  // the *start* path's conflict, and an already-settled room is
  // `invalid_state_transition`, a business rule violation. Observed on a
  // device: every one of four rooms settled itself as `client_disconnect`
  // before the End tap landed, and the server answered 422 each time.
  const { sessions } = api({
    ok: false,
    status: 422,
    json: async () => ({
      error: { code: 'invalid_state_transition', message: 'That session cannot move to that state.' },
    }),
  });

  await expect(sessions.end('session-1')).resolves.toBeUndefined();
});

it('reports a signed-out session as such, rather than as a dead room', async () => {
  const { sessions } = api({ ok: false, status: 401 });

  await expect(sessions.start({ archetypes: [], materialIds: [] })).rejects.toBeInstanceOf(
    SignedOut
  );
});

describe('a room the server will not open', () => {
  /**
   * Reported from a device as "the room would not open, nothing was charged".
   *
   * The server had said exactly what was wrong — `no_minutes_remaining`, "You
   * are out of interrogation minutes" — and this client threw the body away
   * unread, raising a bare Error with a status code in it. The screen then had
   * nothing to say but its catch-all.
   *
   * A refusal somebody can act on is worth more than any amount of graceful
   * failure, and the server had already done the work.
   */
  it('carries the code the server refused with', async () => {
    const { sessions } = api({
      ok: false,
      status: 422,
      json: async () => ({
        error: {
          code: 'no_minutes_remaining',
          message: 'You are out of interrogation minutes.',
        },
      }),
    });

    await expect(
      sessions.start({ archetypes: ['cfo'], materialIds: [] })
    ).rejects.toMatchObject({ code: 'no_minutes_remaining' });
  });

  it('still fails loudly when the body explains nothing', async () => {
    // A gateway, a proxy, anything between the phone and the API. There is no
    // code to carry, and inventing one would send the screen down a path the
    // server never asked for.
    const { sessions } = api({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error('not json');
      },
    });

    await expect(
      sessions.start({ archetypes: ['cfo'], materialIds: [] })
    ).rejects.toThrow();
  });
});

describe('the rooms already run', () => {
  /**
   * The Library, and the two things it is for: reading a room back, and
   * running it again.
   *
   * `GET /v1/sessions` has existed since the endpoints were built and nothing
   * has ever called it. It is the only place a client can learn that a past
   * room existed, which seating it had, and whether it can still be heard.
   */
  const ROOM = {
    id: 'session-9',
    user_id: 'user-1',
    state: 'settled',
    started_at: '2026-08-19T20:39:35Z',
    end_reason: 'user_ended',
    settled_at: '2026-08-19T20:51:02Z',
    material_ids: ['m-7'],
    archetypes: ['cfo', 'technical_skeptic'],
    recording: { state: 'available', expires_at: '2026-09-18T20:51:02Z' },
  };

  it('lists this account’s rooms, newest first, without asking whose', async () => {
    // Never a user id in the query. A list endpoint that took one would be an
    // authorisation check waiting to be forgotten — the server scopes it to
    // the credential, and the client must not imply otherwise.
    const { fetcher, sessions } = api({ json: async () => [ROOM] });

    const rooms = await sessions.list();

    expect(fetcher.mock.calls[0][0]).toBe('https://flintroom.test/v1/sessions');
    expect(rooms).toHaveLength(1);
    expect(rooms[0].id).toBe('session-9');
  });

  it('carries what a room needs to be run again', async () => {
    // The whole reason re-running needs no new endpoint. Seating and grounding
    // are both here, so "run this again" is a `start` with the values already
    // in hand — and the source document being long deleted does not matter,
    // because the extracted claims are what a room is grounded in.
    const { sessions } = await api({ json: async () => [ROOM] });

    const [room] = await sessions.list();

    expect(room.archetypes).toEqual(['cfo', 'technical_skeptic']);
    expect(room.materialIds).toEqual(['m-7']);
  });

  it('says whether a room can still be heard, and until when', async () => {
    // Three states rather than a nullable URL, because two of them are
    // ordinary and mean different things: a retention window arriving on
    // schedule is not the same as saving having been switched off, and telling
    // somebody the first when the second is true reads as data loss.
    const { sessions } = api({ json: async () => [ROOM] });

    const [room] = await sessions.list();

    expect(room.recording).toEqual({
      state: 'available',
      expiresAt: '2026-09-18T20:51:02Z',
    });
  });

  it('survives a room that was never recorded and never settled', async () => {
    // Both are ordinary. A room can end before the panel says anything, and
    // saving can be off — neither is missing data, and a client that assumed
    // the fields were there would crash the Library on the most common row.
    const { sessions } = api({
      json: async () => [
        {
          id: 'session-1',
          user_id: 'user-1',
          state: 'failed',
          started_at: '2026-08-19T19:02:27Z',
        },
      ],
    });

    const [room] = await sessions.list();

    expect(room.settledAt).toBeNull();
    expect(room.archetypes).toEqual([]);
    expect(room.materialIds).toEqual([]);
    expect(room.recording.state).toBe('not_recorded');
  });

  it('reports a signed-out session as such rather than as an empty library', async () => {
    // An empty array and a signed-out account look identical on the screen,
    // and only one of them is a reason to send somebody to sign in again.
    const { sessions } = api({ ok: false, status: 401 });

    await expect(sessions.list()).rejects.toBeInstanceOf(SignedOut);
  });
});
