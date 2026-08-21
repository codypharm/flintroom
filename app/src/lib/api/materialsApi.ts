import { SignedOut } from '../auth/session';

/**
 * Attaching a deck: three calls, then a wait.
 *
 * The handshake is `docs/ingestion.md`'s, and the shape is not incidental. The
 * row precedes the object, so registering comes first and returns the one URL
 * that may fill it. The bytes then go **straight to storage** — `CLAUDE.md`
 * forbids proxying uploaded material through a request handler, and a hundred
 * megabytes of somebody's deck has no business inside a worker. Only then does
 * the server check the object really landed, which is the moment the material
 * becomes extractable and starts costing money.
 *
 * Skipping the last call is the failure worth naming: the row sits in
 * `awaiting_upload`, no sweep will ever claim it, and the user watches a deck
 * that is never read.
 */

/** The three states a person waiting can actually be shown. */
export type AttachedState = 'extracting' | 'ready' | 'failed';

export interface AttachedMaterial {
  id: string;
  filename: string;
  state: AttachedState;
}

/** What the OS picker hands back, narrowed to what the handshake needs. */
export interface PickedFile {
  uri: string;
  name: string;
  mimeType?: string | null;
  size?: number | null;
}

/**
 * What this account may upload, published so the screen can say it up front.
 *
 * The endpoint exists for exactly this: "so the app can refuse an oversized
 * file locally, before it reads a byte", with the server refusal still the real
 * wall. Shipping the tier table in an app release instead is how a pricing
 * change and the picker start disagreeing with nobody noticing.
 */
export interface MaterialLimits {
  tier: string;
  maxUploadBytes: number;
  maxPagesPerMaterial: number;
  acceptedContentTypes: string[];
}

export interface MaterialsApi {
  attach(file: PickedFile, read: (uri: string) => Promise<Blob>): Promise<AttachedMaterial>;
  state(id: string): Promise<AttachedState>;
  /**
   * A material this account already owns, enough of it to draw as attached.
   *
   * Exists for re-running a past room, which carries material *ids* and nothing
   * else. `state` fetches the same resource and keeps only the state, so the
   * filename — the one thing that tells somebody the right deck is attached —
   * was being thrown away.
   *
   * Raises rather than returning null when it is gone, which is ordinary: a
   * deck can be deleted from Settings after the room that used it, and a
   * re-run should then offer the panel without the material rather than a room
   * grounded in nothing while claiming otherwise.
   */
  read(id: string): Promise<AttachedMaterial>;
  limits(): Promise<MaterialLimits>;
  /**
   * Everything this account still has attached, newest first.
   *
   * Settings owes somebody a straight answer to "what do you hold", and until
   * the endpoint existed the only way to name a material was to have kept the
   * response that registered it. An empty list is a real answer, not a failure.
   */
  list(): Promise<AttachedMaterial[]>;
  /**
   * Destroy a material and everything extracted from it.
   *
   * Local state is not enough. `docs/ingestion.md` has the source document
   * deleted once extraction succeeds but the claims outlive it, and a session
   * started against a material this account still owns can still be grounded in
   * it — so a Remove that only cleared a variable would be a screen saying the
   * deck is gone while the room still quotes from it.
   *
   * A second call is a 404 by design, and that is treated as success: the thing
   * the caller wanted gone is gone.
   */
  remove(id: string): Promise<void>;
}

export interface MaterialsApiOptions {
  baseUrl: string;
  accessToken(): Promise<string>;
  fetch?: typeof fetch;
}

/**
 * Five server states, three a screen can draw.
 *
 * `awaiting_upload`, `pending` and `extracting` are one fact to somebody
 * watching — not yet — and collapsing them here rather than in a component
 * keeps `MaterialState`'s vocabulary in one place. The distinction the server
 * draws between them is about which sweep may claim a row, which is not a
 * thing a person is waiting on.
 */
function drawable(state: string): AttachedState {
  if (state === 'ready') return 'ready';
  if (state === 'failed') return 'failed';
  return 'extracting';
}

export function createMaterialsApi({
  baseUrl,
  accessToken,
  fetch: fetcher = fetch,
}: MaterialsApiOptions): MaterialsApi {
  const send = async (path: string, init: RequestInit = {}): Promise<Response> => {
    const response = await fetcher(`${baseUrl}${path}`, {
      ...init,
      headers: {
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        Authorization: `Bearer ${await accessToken()}`,
      },
    });

    if (response.status === 401) {
      throw new SignedOut(`refused by ${path}`);
    }
    if (!response.ok) {
      // The status is carried because these mean different things to a user: a
      // 413 is a deck too big for the plan, a 415 is a file we cannot read, and
      // a 502 is us. The screen decides the sentence.
      throw new Error(`${path} failed with ${response.status}`);
    }

    return response;
  };

  return {
    attach: async (file, read) => {
      const contentType = file.mimeType ?? 'application/pdf';

      const registered = (await (
        await send('/v1/materials', {
          method: 'POST',
          body: JSON.stringify({
            filename: file.name,
            content_type: contentType,
            byte_size: file.size ?? 0,
          }),
        })
      ).json()) as { id: string; filename: string; upload_url: string };

      // Direct to storage, never through us. The URL is signed for exactly this
      // length and type, so a body of a different size is refused by the store
      // itself rather than by a check somebody could forget.
      const put = await fetcher(registered.upload_url, {
        method: 'PUT',
        headers: { 'Content-Type': contentType },
        body: await read(file.uri),
      });
      if (!put.ok) {
        throw new Error(`upload failed with ${put.status}`);
      }

      const completed = (await (
        await send(`/v1/materials/${registered.id}/complete`, { method: 'POST' })
      ).json()) as { state: string };

      return {
        id: registered.id,
        filename: registered.filename,
        state: drawable(completed.state),
      };
    },

    limits: async () => {
      const read = (await (await send('/v1/materials/limits')).json()) as {
        tier: string;
        max_upload_bytes: number;
        max_pages_per_material: number;
        accepted_content_types: string[];
      };

      return {
        tier: read.tier,
        maxUploadBytes: read.max_upload_bytes,
        maxPagesPerMaterial: read.max_pages_per_material,
        acceptedContentTypes: read.accepted_content_types,
      };
    },

    remove: async (id) => {
      const response = await fetcher(`${baseUrl}/v1/materials/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${await accessToken()}` },
      });

      // 404 is success here. The material is not found from the moment of the
      // request that deleted it, so a retry after a dropped response must not
      // report a failure for work that was already done.
      if (response.ok || response.status === 404) return;
      if (response.status === 401) throw new SignedOut('refused by DELETE /v1/materials');

      throw new Error(`DELETE /v1/materials failed with ${response.status}`);
    },

    read: async (id) => {
      const response = await send(`/v1/materials/${id}`);

      if (!response.ok) {
        throw new Error(`material ${id} could not be read: ${response.status}`);
      }

      const body = (await response.json()) as { id: string; filename: string; state: string };

      return { id: body.id, filename: body.filename, state: drawable(body.state) };
    },

    state: async (id) => {
      const body = (await (await send(`/v1/materials/${id}`)).json()) as {
        state: string;
      };
      return drawable(body.state);
    },

    list: async () => {
      const rows = (await (await send('/v1/materials')).json()) as {
        id: string;
        filename: string;
        state: string;
      }[];

      return rows.map((row) => ({
        id: row.id,
        filename: row.filename,
        state: drawable(row.state),
      }));
    },
  };
}
