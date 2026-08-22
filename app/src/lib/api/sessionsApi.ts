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
  /**
   * The rehearsal this room belongs to — its own id unless it repeats another.
   *
   * Never null, so grouping and lineage lookups have no special case.
   */
  rehearsalId: string;
  /**
   * What the presenter calls the rehearsal this room belongs to, or null.
   *
   * The **lineage's** name, not this room's. A re-run reports the name it
   * inherited even though nobody typed one into it, and naming a rehearsal on
   * its fourth attempt names all four.
   */
  rehearsalName: string | null;
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
  /**
   * What the presenter said about the room they were facing, or null.
   *
   * **This room's own, never the lineage's** — unlike `rehearsalName` above.
   * The same argument may go to a VP on Monday and a board on Friday: one
   * rehearsal, two audiences. Read by the setup screen so a re-run arrives with
   * the note already in the box, where somebody can change it before Start.
   */
  audience: string | null;
  /**
   * The rung this room ran at, or null if it never became a room.
   *
   * Read by the setup screen so a re-run can *show* the pressure it will
   * actually open at — a room that repeats another inherits the rung its
   * rehearsal last ran at, and a picker showing the account's number would
   * state one thing and start another.
   */
  difficultyLevel: number | null;
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
   * as they are said, so it is close, and "close" is exactly the difference
   * `beganAtSeconds` below exists about.
   */
  saidAt: string;

  /**
   * How many seconds into the **saved recording** this line began, or null.
   *
   * #69. A position in the file `playback` signs a link to, taken from the
   * room's own mixer while it ran — so this may be handed straight to a seek.
   * `saidAt` above cannot: it is a wall clock, and turning one into the other
   * would mean subtracting a session start this screen does not have and
   * assuming nothing stalled in between.
   *
   * **Null is a real answer.** Every room recorded before this existed has no
   * offset. Treat it as "no anchor" and fall back to playing the room from the
   * top; a client that read it as `0` would offer to jump to the start of the
   * room on every line — a control that looks like it works and does the wrong
   * thing.
   */
  beganAtSeconds: number | null;
}

export interface StartRoom {
  /** Archetype names, as the catalogue spells them. Empty seats the default panel. */
  archetypes: string[];
  materialIds: string[];
  /**
   * What the presenter calls what they are rehearsing, or null.
   *
   * Optional, and never required to re-run: a room that repeats another
   * inherits its lineage's name server-side, so sending it back is a round trip
   * that exists only to let a client get it wrong.
   */
  rehearsalName: string | null;
  /**
   * What the presenter says about the room they are walking into, or null.
   *
   * #66. Unlike `rehearsalName` this is **not** inherited server-side: it
   * belongs to the room rather than to the lineage, so a re-run sends back what
   * the setup screen prefilled and the presenter may have changed.
   *
   * The only field on this request whose text reaches a model. The server
   * fences it as data before it does, and the panel is shaped by it without
   * ever repeating it aloud.
   */
  audience: string | null;
  /**
   * The room this one is a re-run of, or null when the argument is a new one.
   *
   * The server resolves it to a rehearsal and files the new room under the same
   * one, so a run of attempts at the same argument reads as a run rather than
   * as unrelated rooms that happen to share a panel.
   *
   * A *room* id, never a rehearsal id. The server checks it against ownership
   * and answers 404 for a room this account did not run — a group id taken
   * straight from the request would let a rehearsal be filed into somebody
   * else's history, and a progress screen would then average two people.
   */
  repeats: string | null;
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
  /**
   * Destroy one room's audio, because the presenter asked.
   *
   * **The transcript survives**, and that is the server's decision rather than
   * this client's — the two artefacts have separate lifetimes by design, and
   * taking the debrief's grounding along with the audio would be a second,
   * unasked-for deletion. Nothing here can widen it: the endpoint takes no
   * body, so a client cannot choose how much of a room to destroy.
   *
   * Idempotent. The server answers 204 whether or not there was anything
   * there, and a room that is gone answers 404 — both mean the thing the caller
   * wanted gone is gone.
   */
  deleteRecording(sessionId: string): Promise<void>;
  /**
   * A short-lived link to hear one room again.
   *
   * **Called at the moment somebody taps play, never on the way in.** The link
   * lives fifteen minutes (`DEFAULT_EXPIRY_SECONDS`), and a screen that
   * presigned on load would hand a dead URL to anybody who read the transcript
   * first — which is what this screen is mostly for. Signing costs nothing and
   * a stale link costs a failure nobody can act on.
   *
   * Refuses distinctly for a room with nothing stored: recording can be off by
   * preference, expired on the tier window, or deleted from this very screen a
   * moment ago, and none of those is the same sentence as a store that could
   * not be reached.
   */
  playback(sessionId: string): Promise<Playback>;
}

/**
 * Where a room can be heard, and for how long that stays true.
 *
 * `expiresInSeconds` is published rather than folded into an absolute time
 * because it is what the server actually knows — the two clocks are not the
 * same, and a phone that is a minute out would silently shorten or extend a
 * window it does not own.
 */
export interface Playback {
  url: string;
  expiresInSeconds: number;
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
    start: async ({ archetypes, materialIds, repeats, rehearsalName, audience }) => {
      const response = await send('/v1/sessions', {
        method: 'POST',
        body: JSON.stringify({
          archetypes,
          material_ids: materialIds,
          // Omitted rather than sent as null. The field is optional on the
          // server, and a room that repeats nothing has nothing to say here.
          ...(repeats === null ? {} : { repeats }),
          ...(rehearsalName === null ? {} : { rehearsal_name: rehearsalName }),
          ...(audience === null ? {} : { audience }),
        }),
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
        beganAtSeconds: line.began_at_seconds,
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

    playback: async (sessionId) => {
      const path = `/v1/sessions/${sessionId}/recording`;
      const response = await send(path, { method: 'GET' });

      if (!response.ok) {
        // The server's own diagnosis first. `recording_not_available` is the
        // one the screen switches on, and throwing it away would leave a room
        // whose audio expired reading the same as a store that fell over.
        throw (await refusalIn(response)) ?? new Error(`${path} failed with ${response.status}`);
      }

      const body = (await response.json()) as { url: string; expires_in_seconds: number };

      return { url: body.url, expiresInSeconds: body.expires_in_seconds };
    },

    deleteRecording: async (sessionId) => {
      const path = `/v1/sessions/${sessionId}/recording`;
      const response = await send(path, { method: 'DELETE' });

      // A 404 is a room that is already gone, which is the state the caller
      // asked for. Reporting it as a failure sends somebody back to try again
      // at something that has already succeeded.
      if (response.ok || response.status === 404) return;

      throw new Error(`${path} failed with ${response.status}`);
    },
  };
}


interface SaidLineBody {
  ordinal: number;
  speaker: string;
  text: string;
  said_at: string;
  began_at_seconds: number | null;
}

/** The wire's spelling, before the app renames it. */
interface PastRoomBody {
  id: string;
  rehearsal_id: string;
  rehearsal_name?: string | null;
  difficulty_level?: number | null;
  state: string;
  started_at: string;
  end_reason?: string | null;
  settled_at?: string | null;
  archetypes?: string[];
  material_ids?: string[];
  audience?: string | null;
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
    rehearsalId: room.rehearsal_id,
    rehearsalName: room.rehearsal_name ?? null,
    difficultyLevel: room.difficulty_level ?? null,
    state: room.state,
    startedAt: room.started_at,
    endReason: room.end_reason ?? null,
    settledAt: room.settled_at ?? null,
    archetypes: room.archetypes ?? [],
    materialIds: room.material_ids ?? [],
    audience: room.audience ?? null,
    recording: {
      state: (room.recording?.state ?? 'not_recorded') as RoomRecording['state'],
      expiresAt: room.recording?.expires_at ?? null,
    },
  };
}
