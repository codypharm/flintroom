import { createMaterialsApi } from './materialsApi';

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
