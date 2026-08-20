import { SignedOut } from '../auth/session';

/**
 * The panelists this account wrote.
 *
 * Its own client rather than a method on `panelsApi`, which reads the roster we
 * ship. These are rows somebody owns and can change; the two share a base URL
 * and nothing else.
 *
 * `docs/custom-archetypes.md` is the resolved design. Two of its decisions
 * surface here rather than staying on the server, because a client that does not
 * know them behaves wrongly:
 *
 * - **A revision may come back with a different `name`.** A panelist that has
 *   been in a room is replaced rather than edited, so past rooms keep pointing
 *   at the text that was actually in them. A caller that assumed the name
 *   survived would hold a stale one.
 * - **Retiring is an archive.** The row stays so every past room can still say
 *   who was in it, which is why the control that calls this must read *remove
 *   from your panel* and never *delete*.
 */

/** One panelist somebody wrote, as their own device sees it. */
export interface MyArchetype {
  /** `custom:{uuid}` — minted by the server, and what seats it in a room. */
  name: string;
  title: string;
  /** Their own words. The attack strategy we compose around it never leaves. */
  persona: string;
  domains: string[];
  /** One of ours, or null for "pick one for me". */
  voice: string | null;
}

/** What the form sends. Every field, every time — the server takes a whole one. */
export interface ArchetypeDraft {
  title: string;
  persona: string;
  domains: string[];
  voice: string | null;
}

/**
 * A refusal the form has to render beside a field rather than as a failure.
 *
 * Only the ones a person can act on. Everything else is an `Error`, because a
 * form cannot help with a 500 and pretending otherwise puts a fixable-looking
 * message under a control that will refuse again.
 */
export class TitleAlreadyUsed extends Error {}
export class NotYourPlan extends Error {}

export interface ArchetypesApi {
  mine(): Promise<MyArchetype[]>;
  write(draft: ArchetypeDraft): Promise<MyArchetype>;
  revise(name: string, draft: ArchetypeDraft): Promise<MyArchetype>;
  retire(name: string): Promise<void>;
}

export interface ArchetypesApiOptions {
  baseUrl: string;
  accessToken(): Promise<string>;
  fetch?: typeof fetch;
}

export function createArchetypesApi({
  baseUrl,
  accessToken,
  fetch: fetcher = fetch,
}: ArchetypesApiOptions): ArchetypesApi {
  const mine = `${baseUrl}/v1/archetypes/mine`;

  const headers = async () => ({
    Authorization: `Bearer ${await accessToken()}`,
    'Content-Type': 'application/json',
  });

  const refused = async (response: Response, what: string): Promise<never> => {
    if (response.status === 401) {
      throw new SignedOut(`refused by ${what}`);
    }
    if (response.status === 403) {
      throw new NotYourPlan('writing your own panelist is a Pro capability');
    }

    // The code, not the status. 422 is also what a too-long persona returns,
    // and the two want different words under different controls.
    const body = await response.json().catch(() => null);
    if (body?.error?.code === 'title_already_used') {
      throw new TitleAlreadyUsed('you already have a panelist with that name');
    }

    throw new Error(`${what} failed with ${response.status}`);
  };

  const read = (row: MyArchetype): MyArchetype => ({
    name: row.name,
    title: row.title,
    persona: row.persona,
    domains: row.domains,
    voice: row.voice,
  });

  return {
    mine: async () => {
      const response = await fetcher(mine, { headers: await headers() });
      if (!response.ok) return refused(response, '/v1/archetypes/mine');
      return ((await response.json()) as MyArchetype[]).map(read);
    },

    write: async (draft) => {
      const response = await fetcher(mine, {
        method: 'POST',
        headers: await headers(),
        body: JSON.stringify(draft),
      });
      if (!response.ok) return refused(response, 'writing a panelist');
      return read((await response.json()) as MyArchetype);
    },

    revise: async (name, draft) => {
      const response = await fetcher(`${mine}/${encodeURIComponent(name)}`, {
        method: 'PUT',
        headers: await headers(),
        body: JSON.stringify(draft),
      });
      if (!response.ok) return refused(response, 'editing a panelist');
      // Read the answer rather than assuming the request. A seated panelist
      // comes back under a new name.
      return read((await response.json()) as MyArchetype);
    },

    retire: async (name) => {
      const response = await fetcher(`${mine}/${encodeURIComponent(name)}`, {
        method: 'DELETE',
        headers: await headers(),
      });
      if (!response.ok) await refused(response, 'removing a panelist');
    },
  };
}
