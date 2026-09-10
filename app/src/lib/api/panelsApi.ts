import { SignedOut } from '../auth/session';
import { boundedFetch } from '../net/bounded';

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
  /**
   * Who the survey already put in the chairs, in seat order.
   *
   * The reveal. Derived on the server from the answers rather than assembled
   * here, so the room shown is the room a session will build — a client-side
   * map would be a second copy free to disagree across a release, which is the
   * failure `/v1/archetypes` exists to prevent for the roster itself.
   *
   * Never empty: an account that answered nothing falls through to the shipped
   * default panel, so no screen needs a branch for it.
   */
  seated: string[];
  seats: number;
  mayAuthor: boolean;
  upgradeSeats: number | null;
  /**
   * Every claim domain a panelist may own, sorted.
   *
   * Carried on this response rather than fetched by the authoring form,
   * because the form is opened from the screen that already made this request.
   * Never a constant in the app: these are the Auditor's routing key and the
   * server refuses one it does not route on, so a copied list is a form
   * offering choices the API rejects.
   */
  domains: { name: string; label: string }[];
  /** The voices a panelist may be cast in, and what each sounds like. */
  voices: { name: string; label: string; sounds: string }[];
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
  domains?: { name: string; label: string }[];
  voices?: { name: string; label: string; sounds: string }[];
  seated?: string[];
  seats: number;
  may_author: boolean;
  upgrade_seats: number | null;
  difficulty: number;
  hardest: number;
}

export function createPanelsApi({
  baseUrl,
  accessToken,
  fetch: fetcher = boundedFetch(),
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
        seated: body.seated ?? [],
        seats: body.seats,
        mayAuthor: body.may_author,
        upgradeSeats: body.upgrade_seats,
        // Defaulted rather than required, matching `seated` above: a server one
        // release behind simply offers nothing to choose from, which the form
        // renders as an empty list rather than crashing the screen that opened
        // it.
        domains: body.domains ?? [],
        voices: body.voices ?? [],
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
