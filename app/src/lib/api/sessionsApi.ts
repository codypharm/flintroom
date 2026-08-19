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

/**
 * Whether a room can still be heard, and until when.
 *
 * Three states rather than a nullable URL, because two of them are ordinary and
 * mean different things to whoever is reading the screen: a retention window
 * arriving exactly on schedule is not the same as saving having been switched
 * off, and saying the first when the second is true reads as data loss.
 */
export interface RoomRecording {
  state: 'available' | 'expired' | 'not_recorded';
  /** ISO 8601, or null when there is nothing to expire. */
  expiresAt: string | null;
}

/** A room that has already happened. */
export interface PastRoom {
  id: string;
  state: string;
  startedAt: string;
  /**
   * How it ended, or null while it is still running.
   *
   * Read with care on a screen. Every room in the dev database settled as
   * `client_disconnect` (#82) because the End tap loses a race with the socket
   * closing — so a reason must not be drawn as an accusation or as an error
   * until that is fixed.
   */
  endReason: string | null;
  settledAt: string | null;
  /** Who was seated, in the order they spoke. Enough to seat the room again. */
  archetypes: string[];
  /**
   * What it was grounded in. Enough to ground the room again — the source
   * document is deleted once extraction succeeds, but the claims it produced
   * are what a room actually reads.
   */
  materialIds: string[];
  recording: RoomRecording;
}

/** One line of one room, as it was said. */
export interface SaidLine {
  /** Where it falls in the room, from zero. The order is content, not display. */
  ordinal: number;
  /** `user`, or an archetype's name. Resolved against the catalogue for display. */
  speaker: string;
  text: string;
  /**
   * When the line was **written**, which is not when the audio was heard.
   *
   * Enough to orient a reader — a room reads differently when you can see where
   * the long silence was — and not enough to seek audio with. Lines are written
   * as they are said, so it is close, and "close" is exactly the difference #69
   * exists about.
   */
  saidAt: string;
}

export interface StartRoom {
  /** Archetype names, as the catalogue spells them. Empty seats the default panel. */
  archetypes: string[];
  materialIds: string[];
}

export interface SessionsApi {
  start(room: StartRoom): Promise<StartedRoom>;
  /**
   * Every room this account has run, newest first.
   *
   * Never takes a user id. The server scopes it to the credential, and a
   * parameter here would imply an authorisation check that a caller could
   * forget to make.
   *
   * Carries no transcript and no audio — `CLAUDE.md` keeps both out of list
   * responses — only whether each room can still be heard, and until when.
   */
  list(): Promise<PastRoom[]>;
  /**
   * Every line of one room, in the order it happened.
   *
   * An empty array is a real answer: a room can end before the panel gets a
   * question out, and that is the commonest shape in a fresh account.
   */
  transcript(sessionId: string): Promise<SaidLine[]>;
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

    list: async () => {
      const rooms = (await (
        await send('/v1/sessions', { method: 'GET' })
      ).json()) as PastRoomBody[];

      return rooms.map(asPastRoom);
    },

    transcript: async (sessionId) => {
      const body = (await (
        await send(`/v1/sessions/${sessionId}/transcript`, { method: 'GET' })
      ).json()) as { lines: SaidLineBody[] };

      return body.lines.map((line) => ({
        ordinal: line.ordinal,
        speaker: line.speaker,
        text: line.text,
        saidAt: line.said_at,
      }));
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


interface SaidLineBody {
  ordinal: number;
  speaker: string;
  text: string;
  said_at: string;
}

/** The wire's spelling, before the app renames it. */
interface PastRoomBody {
  id: string;
  state: string;
  started_at: string;
  end_reason?: string | null;
  settled_at?: string | null;
  archetypes?: string[];
  material_ids?: string[];
  recording?: { state: string; expires_at?: string | null };
}

/**
 * One row, with every optional field given a real value.
 *
 * The server omits rather than nulls: a room that ended before the panel spoke
 * has no archetypes key at all, and one started with saving off has no
 * recording. Both are ordinary — the commonest row in a fresh account is a room
 * that failed to provision — so a screen that assumed the fields were present
 * would crash on exactly the rooms most likely to be there.
 */
function asPastRoom(room: PastRoomBody): PastRoom {
  return {
    id: room.id,
    state: room.state,
    startedAt: room.started_at,
    endReason: room.end_reason ?? null,
    settledAt: room.settled_at ?? null,
    archetypes: room.archetypes ?? [],
    materialIds: room.material_ids ?? [],
    recording: {
      state: (room.recording?.state ?? 'not_recorded') as RoomRecording['state'],
      expiresAt: room.recording?.expires_at ?? null,
    },
  };
}
