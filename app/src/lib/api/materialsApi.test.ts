import { MaterialGone,createMaterialsApi } from './materialsApi';

/**
 * Attaching a deck, which is three calls and a wait.
 *
 * The handshake is the interesting part and it is easy to get subtly wrong:
 * the row precedes the object, the presigned PUT goes straight to storage
 * rather than through the API, and the material is only extractable once the
 * server has confirmed the bytes landed. A client that skipped `complete`
 * would leave a row the reaper eventually takes, and the user would watch a
 * deck sit at "being read" forever.
 */
function apiOver(handler: (url: string, init: RequestInit) => Response) {
  const calls: { url: string; method: string }[] = [];

  const fetcher = async (url: string, init: RequestInit = {}) => {
    calls.push({ url, method: init.method ?? 'GET' });
    return handler(url, init);
  };

  return {
    api: createMaterialsApi({
      baseUrl: 'https://api.example',
      fetch: fetcher as unknown as typeof fetch,
      accessToken: async () => 'access-1',
    }),
    calls,
  };
}

const ok = (body: unknown) =>
  ({ ok: true, status: 200, json: async () => body }) as Response;

const REGISTERED = {
  id: 'm-1',
  state: 'awaiting_upload',
  filename: 'Q3 board deck.pdf',
  content_type: 'application/pdf',
  byte_size: 12,
  created_at: '2026-08-18T00:00:00Z',
  upload_url: 'https://storage.example/signed-put',
};

const DECK = {
  uri: 'file:///tmp/deck.pdf',
  name: 'Q3 board deck.pdf',
  mimeType: 'application/pdf',
  size: 12,
};

it('registers, uploads straight to storage, then reports the bytes landed', async () => {
  // The order is the contract. The PUT goes to the signed URL rather than to
  // our API — a deck never travels through a request handler — and `complete`
  // is what makes the material extractable, so skipping it leaves a row the
  // reaper takes and a deck that never gets read.
  const { api, calls } = apiOver((url) =>
    url.endsWith('/signed-put')
      ? ({ ok: true, status: 200 } as Response)
      : ok(url.endsWith('/complete') ? { ...REGISTERED, state: 'pending' } : REGISTERED)
  );

  const attached = await api.attach(DECK, async () => new Blob(['pdf']));

  expect(calls.map((call) => `${call.method} ${call.url}`)).toEqual([
    'POST https://api.example/v1/materials',
    'PUT https://storage.example/signed-put',
    'POST https://api.example/v1/materials/m-1/complete',
  ]);
  expect(attached).toEqual({ id: 'm-1', filename: 'Q3 board deck.pdf', state: 'extracting' });
});

it('types the blob it uploads, because the wire takes the type from the blob', async () => {
  // Found on a real phone and invisible to every laptop probe: React Native's
  // networking layer sets a Blob body's Content-Type from the blob itself,
  // overriding the headers object — and a blob read back from the picker's
  // file is untyped. So the PUT went out with an empty Content-Type, the
  // presign's signature (which covers content-type) stopped matching, and
  // storage refused every upload from a device as a 403 the alert rounded off
  // to "could not reach the server". The headers object cannot carry this
  // fact; the blob has to.
  const puts: RequestInit[] = [];
  const fetcher = async (url: string, init: RequestInit = {}) => {
    if (init.method === 'PUT') puts.push(init);
    return url.endsWith('/signed-put')
      ? ({ ok: true, status: 200 } as Response)
      : ok(url.endsWith('/complete') ? { ...REGISTERED, state: 'pending' } : REGISTERED);
  };
  const api = createMaterialsApi({
    baseUrl: 'https://api.example',
    fetch: fetcher as unknown as typeof fetch,
    accessToken: async () => 'access-1',
  });

  await api.attach(DECK, async () => new Blob(['pdf']));

  expect((puts[0]?.body as Blob).type).toBe('application/pdf');
});

it('reports a deck the server refused without pretending it attached', async () => {
  // A file over the tier's cap is refused before anything is signed, so there
  // is no upload to undo — but the screen must not show a deck row for it.
  const { api } = apiOver(() => ({ ok: false, status: 413, json: async () => ({}) }) as Response);

  await expect(api.attach(DECK, async () => new Blob(['pdf']))).rejects.toThrow('413');
});

it('collapses the five server states into the three a screen can draw', async () => {
  // MaterialState has five entries and two of them are the same fact to a
  // person waiting: `pending` and `extracting` both mean "not yet". Mapping
  // here rather than in the component keeps the vocabulary in one place.
  const { api } = apiOver(() => ok({ ...REGISTERED, state: 'ready' }));

  await expect(api.state('m-1')).resolves.toBe('ready');
});

describe('a material a past room was grounded in', () => {
  /**
   * Running a room again means running it against the same material, and a past
   * room carries only ids. `state()` already fetches this exact resource and
   * throws away everything but the state — including the filename, which is the
   * only thing that tells somebody the right deck is attached.
   */
  it('reads back enough to show it as attached', async () => {
    const { api } = apiOver(() =>
      ok({
        id: 'm-7',
        state: 'ready',
        filename: 'Q3 board readout.pdf',
        content_type: 'application/pdf',
        byte_size: 214_000,
      })
    );

    expect(await api.read('m-7')).toEqual({
      id: 'm-7',
      filename: 'Q3 board readout.pdf',
      state: 'ready',
    });
  });

  it('reports a material that is gone rather than inventing one', async () => {
    // Reachable and ordinary: a deck can be deleted from Settings after the
    // room that used it. Re-running should then offer the panel without the
    // material, not a room grounded in nothing while claiming otherwise.
    //
    // Typed, because the caller's two failures need opposite handling: a deck
    // that is *gone* should be dropped from the screen, and a deck behind a
    // network blip must not be — observed live (2026-08-27): a deck deleted in
    // Settings stayed drawn as attached on the setup screen, and Start with it
    // would have been refused by the server.
    const { api } = apiOver(
      () => ({ ok: false, status: 404, json: async () => ({}) }) as Response
    );

    await expect(api.read('m-7')).rejects.toThrow(MaterialGone);
  });

  it('says gone when asked only for the state of a deleted material', async () => {
    const { api } = apiOver(
      () => ({ ok: false, status: 404, json: async () => ({}) }) as Response
    );

    await expect(api.state('m-7')).rejects.toThrow(MaterialGone);
  });
});

describe('what this account still has attached', () => {
  function listing(rows: unknown[]) {
    const fetcher = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => rows,
    });

    return {
      fetcher,
      materials: createMaterialsApi({
        baseUrl: 'https://flintroom.test',
        accessToken: async () => 'a-token',
        fetch: fetcher as unknown as typeof fetch,
      }),
    };
  }

  it('lists it, narrowed to what a screen can draw', async () => {
    const { fetcher, materials } = listing([
      { id: 'm1', filename: 'q3-board-deck.pdf', state: 'ready' },
      { id: 'm2', filename: 'notes.pdf', state: 'pending' },
    ]);

    const mine = await materials.list();

    expect(fetcher.mock.calls[0][0]).toBe('https://flintroom.test/v1/materials');
    // `pending` collapses to `extracting` here as it does everywhere else —
    // three server states are one fact to somebody waiting, and the mapping
    // lives in this file rather than in each screen that reads it.
    expect(mine).toEqual([
      { id: 'm1', filename: 'q3-board-deck.pdf', state: 'ready' },
      { id: 'm2', filename: 'notes.pdf', state: 'extracting' },
    ]);
  });

  it('reports nothing attached as an empty list rather than a failure', async () => {
    const { materials } = listing([]);

    await expect(materials.list()).resolves.toEqual([]);
  });
});

describe('destroying a material the server refuses to destroy', () => {
  function refusing(status: number, body: unknown) {
    const fetcher = jest.fn().mockResolvedValue({
      ok: false,
      status,
      json: async () => body,
    });

    return createMaterialsApi({
      baseUrl: 'https://flintroom.test',
      accessToken: async () => 'a-token',
      fetch: fetcher as unknown as typeof fetch,
    });
  }

  it('carries the refusal the server explained, rather than a status code', async () => {
    /**
     * `material_in_use` is the one refusal here that protects a *session*: the
     * Auditor cross-checks live speech against this material's claims, so
     * pulling it out mid-room leaves somebody paying metered minutes for a
     * panel that has quietly stopped being able to catch anything.
     *
     * The recovery is specific — end the room, then delete — and the server
     * already wrote that sentence. Throwing it away for "failed with 422" is
     * how a screen says "something went wrong" about a problem that was
     * diagnosed.
     */
    const materials = refusing(422, {
      error: {
        code: 'material_in_use',
        message: 'That material is in a room you are still in. End the session first.',
      },
    });

    await expect(materials.remove('m1')).rejects.toMatchObject({
      code: 'material_in_use',
      message: 'That material is in a room you are still in. End the session first.',
    });
  });

  it('still fails plainly when the server explains nothing', async () => {
    // A gateway, a proxy, an HTML error page. There is no sentence to carry and
    // inventing one would put words in the server's mouth.
    const materials = refusing(502, 'not json at all');

    await expect(materials.remove('m1')).rejects.toThrow(/502/);
  });
});
