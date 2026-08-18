import { SignedOut } from '../auth/session';

/**
 * The panel catalogue, over HTTP.
 *
 * The roster is fetched and never shipped inside the app. An archetype added on
 * the server would otherwise need an app release before anybody could seat it,
 * and the two lists would be free to disagree with nothing raising — the same
 * failure the tier table already refused.
 *
 * Written by hand for the reason `authApi` gives: the status-to-error mapping
 * is the substance, and `openapi-fetch` never throws. `schema.d.ts` still types
 * the payloads.
 */

export interface ArchetypeOffered {
  name: string;
  title: string;
  blurb: string;
}

export interface Catalogue {
  archetypes: ArchetypeOffered[];
  seats: number;
  mayAuthor: boolean;
  upgradeSeats: number | null;
  difficulty: number;
  hardest: number;
}

export interface PanelsApi {
  catalogue(): Promise<Catalogue>;
  /** Writes the rung and returns what was stored. */
  chooseDifficulty(level: number): Promise<number>;
}

export interface PanelsApiOptions {
  baseUrl: string;
  accessToken(): Promise<string>;
  fetch?: typeof fetch;
}

/** The catalogue as the wire spells it, before the app renames it. */
interface CatalogueBody {
  archetypes: ArchetypeOffered[];
  seats: number;
  may_author: boolean;
  upgrade_seats: number | null;
  difficulty: number;
  hardest: number;
}

export function createPanelsApi({
  baseUrl,
  accessToken,
  fetch: fetcher = fetch,
}: PanelsApiOptions): PanelsApi {
  const send = async (path: string, init: RequestInit = {}): Promise<Response> => {
    const response = await fetcher(`${baseUrl}${path}`, {
      ...init,
      headers: {
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        Authorization: `Bearer ${await accessToken()}`,
      },
    });

    // The same split every client here draws: a 401 ends the session and
    // anything else is a server we could not reach. A caller that confused them
    // would strand somebody on a setup screen for a minute of downtime.
    if (response.status === 401) {
      throw new SignedOut(`refused by ${path}`);
    }
    if (!response.ok) {
      throw new Error(`${path} failed with ${response.status}`);
    }

    return response;
  };

  return {
    catalogue: async () => {
      const body = (await (await send('/v1/archetypes')).json()) as CatalogueBody;

      return {
        archetypes: body.archetypes,
        seats: body.seats,
        mayAuthor: body.may_author,
        upgradeSeats: body.upgrade_seats,
        difficulty: body.difficulty,
        hardest: body.hardest,
      };
    },

    chooseDifficulty: async (level) => {
      const response = await send('/v1/me/difficulty', {
        method: 'PUT',
        body: JSON.stringify({ difficulty: level }),
      });

      return ((await response.json()) as { difficulty: number }).difficulty;
    },
  };
}
