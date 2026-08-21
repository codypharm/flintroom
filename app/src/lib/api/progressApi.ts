import { SignedOut } from '../auth/session';

/**
 * Whether this account is getting better.
 *
 * Its own client rather than a method on `sessionsApi`, because it is about a
 * *history* rather than about a room: nothing here starts, ends, or reads one,
 * and the two would only ever share a base URL.
 */

/** One assessed room: what it put to them, what held, and how hard it was. */
export interface RoomHeld {
  sessionId: string;
  /**
   * The rehearsal this room belongs to — its own id unless it repeats another.
   *
   * Never null, so grouping is one field with no special case. The column
   * behind it is nullable for migration safety and the server collapses that
   * before it reaches here.
   */
  rehearsalId: string;
  /**
   * What the presenter calls that rehearsal, or null if nobody named it.
   *
   * Null rather than a heading derived from the panel or the deck: a label
   * somebody never chose is one they cannot correct.
   */
  rehearsalName: string | null;
  startedAt: string;
  /**
   * Challenges the presenter actually had a turn at.
   *
   * A question a colleague talked over is in neither term — not a failure, and
   * not a success either, because nobody answered it.
   */
  challenged: number;
  held: number;
  /**
   * The rung this room ran at, or null for one predating the ladder.
   *
   * **Never render `held` without this.** Difficulty escalates, so a room where
   * more got past somebody may simply be a room that pressed harder, and a
   * figure shown bare would tell an improving presenter they are getting worse.
   */
  level: number | null;
}

/** A thing, and how many *rooms* it happened in. */
export interface Tally {
  name: string;
  rooms: number;
}

export interface Progress {
  /** Newest first. */
  rooms: RoomHeld[];
  /** How they fail, commonest first. Only what they were at fault for. */
  habits: Tally[];
  /** Who keeps catching them, commonest first. */
  askers: Tally[];
}

export interface ProgressApi {
  read(): Promise<Progress>;
}

export interface ProgressApiOptions {
  baseUrl: string;
  accessToken(): Promise<string>;
  fetch?: typeof fetch;
}

export function createProgressApi({
  baseUrl,
  accessToken,
  fetch: fetcher = fetch,
}: ProgressApiOptions): ProgressApi {
  return {
    read: async () => {
      const response = await fetcher(`${baseUrl}/v1/progress`, {
        headers: { Authorization: `Bearer ${await accessToken()}` },
      });

      if (response.status === 401) {
        throw new SignedOut('refused by /v1/progress');
      }
      if (!response.ok) {
        throw new Error(`/v1/progress failed with ${response.status}`);
      }

      const body = (await response.json()) as {
        rooms: {
          session_id: string;
          rehearsal_id: string;
          rehearsal_name: string | null;
          started_at: string;
          challenged: number;
          held: number;
          level: number | null;
        }[];
        habits: Tally[];
        askers: Tally[];
      };

      return {
        rooms: body.rooms.map((room) => ({
          sessionId: room.session_id,
          rehearsalId: room.rehearsal_id,
          rehearsalName: room.rehearsal_name,
          startedAt: room.started_at,
          challenged: room.challenged,
          held: room.held,
          level: room.level,
        })),
        habits: body.habits,
        askers: body.askers,
      };
    },
  };
}
