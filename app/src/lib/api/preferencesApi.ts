import { SignedOut } from '../auth/session';

/**
 * Whether rooms are saved, and for how long they stay playable.
 *
 * Its own client rather than a method on `sessionsApi`, even though the route
 * is declared in the sessions module: this is a *preference on the account*,
 * and the two things it answers — a control and a disclosure — belong to the
 * Settings screen rather than to anything that starts or reads a room.
 *
 * The window is read, never sent. `RecordingPreferenceUpdate` carries one
 * field on purpose — a client does not choose its own retention, and a request
 * schema with `retention_days` in it would imply it could.
 */

export interface Recording {
  /** Whether rooms started *after now* are saved. Existing ones are untouched. */
  recordsRooms: boolean;
  /** How long a saved room stays playable, in days. Per tier, so never a literal. */
  retentionDays: number;
}

export interface PreferencesApi {
  read(): Promise<Recording>;
  /**
   * Turn saving on or off for future rooms.
   *
   * Answers with what the server now holds rather than with what was asked, so
   * a caller draws the switch from the truth. `PUT` is idempotent here by
   * design — a toggle tapped twice on a slow connection is the same state.
   */
  setRecordsRooms(enabled: boolean): Promise<Recording>;
}

export interface PreferencesApiOptions {
  baseUrl: string;
  accessToken(): Promise<string>;
  fetch?: typeof fetch;
}

const PATH = '/v1/preferences/recording';

export function createPreferencesApi({
  baseUrl,
  accessToken,
  fetch: fetcher = fetch,
}: PreferencesApiOptions): PreferencesApi {
  const send = async (init: RequestInit = {}): Promise<Recording> => {
    const response = await fetcher(`${baseUrl}${PATH}`, {
      ...init,
      headers: {
        ...(init.body === undefined ? {} : { 'content-type': 'application/json' }),
        Authorization: `Bearer ${await accessToken()}`,
      },
    });

    // Only a 401 is a dead credential. Reading an unreachable server as one is
    // how somebody gets signed out of a good account on a train — and here it
    // would additionally read as "your rooms are not being saved", which is the
    // reassuring direction to be wrong in.
    if (response.status === 401) {
      throw new SignedOut(`refused by ${PATH}`);
    }
    if (!response.ok) {
      throw new Error(`${PATH} failed with ${response.status}`);
    }

    const body = (await response.json()) as {
      records_rooms: boolean;
      retention_days: number;
    };

    return { recordsRooms: body.records_rooms, retentionDays: body.retention_days };
  };

  return {
    read: () => send(),
    setRecordsRooms: (enabled) =>
      send({ method: 'PUT', body: JSON.stringify({ records_rooms: enabled }) }),
  };
}
