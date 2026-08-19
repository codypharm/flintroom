import { SignedOut } from '../auth/session';
import { refusalIn } from './refused';

/**
 * The door into a metered room, and the way out of one.
 *
 * Only two calls: everything that happens *inside* a room travels on the
 * socket, which OpenAPI cannot describe and `docs/voice-stream-protocol.md`
 * owns instead. These are the HTTP bookends.
 *
 * Written by hand for the reason `panelsApi` and `debriefApi` give, and with
 * one of its own: both of these run while a microphone is open and a person is
 * waiting, so what matters is not the happy path but which failures are worth
 * stopping a room for. Exactly one is — a signed-out session.
 */

/** A room that exists, and the single-use ticket that opens its socket. */
export interface StartedRoom {
  id: string;
  /**
   * Spend it on the stream socket, once, within seconds.
   *
   * Named for what it opens rather than `token`, matching the server, so it is
   * never mistaken for the credential that authenticates everything else.
   */
  streamTicket: string;
  /**
   * Who the server seated, in the order they will speak.
   *
   * Echoed back rather than assumed from the request: seating is the server's
   * decision, and the screen draws a tray per seat.
   */
  archetypes: string[];
}

export interface StartRoom {
  /** Archetype names, as the catalogue spells them. Empty seats the default panel. */
  archetypes: string[];
  materialIds: string[];
}

export interface SessionsApi {
  start(room: StartRoom): Promise<StartedRoom>;
  /**
   * The End button, as an intent the server honours.
   *
   * Carries no reason. `user_ended` is the only ending a client is in a
   * position to report, and every other value in the server's enum decides
   * whether minutes are refunded — a client that could name one would be
   * choosing its own refund.
   *
   * Worth calling rather than just closing the socket, which is what the old
   * instrument screen did: a dropped connection settles as `client_disconnect`,
   * and the server's own enum says these are not equivalent to the business.
   */
  end(sessionId: string): Promise<void>;
}

export interface SessionsApiOptions {
  baseUrl: string;
  accessToken(): Promise<string>;
  fetch?: typeof fetch;
}

interface StartedBody {
  id: string;
  stream_ticket: string;
  archetypes?: string[];
}

export function createSessionsApi({
  baseUrl,
  accessToken,
  fetch: fetcher = fetch,
}: SessionsApiOptions): SessionsApi {
  const send = async (path: string, init: RequestInit): Promise<Response> => {
    const response = await fetcher(`${baseUrl}${path}`, {
      ...init,
      headers: {
        ...(init.body === undefined ? {} : { 'content-type': 'application/json' }),
        Authorization: `Bearer ${await accessToken()}`,
      },
    });

    if (response.status === 401) {
      throw new SignedOut(`refused by ${path}`);
    }

    return response;
  };

  return {
    start: async ({ archetypes, materialIds }) => {
      const response = await send('/v1/sessions', {
        method: 'POST',
        body: JSON.stringify({ archetypes, material_ids: materialIds }),
      });

      if (!response.ok) {
        // The server's own diagnosis, kept. It refuses a start for reasons the
        // presenter can act on — out of minutes, a room already running, a
        // panel their plan does not seat — and throwing the body away left the
        // screen with nothing to say but its catch-all. Reported from a device
        // as "the room would not open, nothing was charged" when the server had
        // said exactly which of those it was.
        throw (
          (await refusalIn(response)) ??
          new Error(`${'/v1/sessions'} failed with ${response.status}`)
        );
      }

      const body = (await response.json()) as StartedBody;

      return {
        id: body.id,
        streamTicket: body.stream_ticket,
        archetypes: body.archetypes ?? [],
      };
    },

    end: async (sessionId) => {
      // Nothing is thrown for a refusal, and that is the decision rather than
      // laziness. This is called on the way out of a room that is already over
      // for the person in it: minutes tick in arrears, so the ledger is already
      // correct whatever happens here, and the socket closing races this call
      // by design — a room can settle underneath it. The only thing a failure
      // could change is the recorded reason, and stranding somebody on a dark
      // screen over that would be the worse outcome.
      await send(`/v1/sessions/${sessionId}/end`, { method: 'POST' });
    },
  };
}
