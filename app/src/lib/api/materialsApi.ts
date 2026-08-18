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

export interface MaterialsApi {
  attach(file: PickedFile, read: (uri: string) => Promise<Blob>): Promise<AttachedMaterial>;
  state(id: string): Promise<AttachedState>;
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

    state: async (id) => {
      const body = (await (await send(`/v1/materials/${id}`)).json()) as {
        state: string;
      };
      return drawable(body.state);
    },
  };
}
