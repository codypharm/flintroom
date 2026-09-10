import { REQUEST_TIMEOUT_MS, UPLOAD_TIMEOUT_MS, boundedFetch } from './bounded';

/**
 * Every request gets a deadline, because a request without one can hang
 * forever and did.
 *
 * Measured on an emulator with the network removed, 2026-09-10: the Library
 * spun for eight minutes and never showed a message. Nothing was broken in the
 * screen — its failure branch is written and correct — it simply never ran,
 * because the fetch never settled. A network that *refuses* traffic produces a
 * rejection; one that silently drops it produces nothing at all, and dropping
 * is what a captive portal, a dead cell edge, and a disabled emulator radio
 * all do.
 *
 * This is what makes the offline sentences reachable. `isOffline` explains a
 * failure; it cannot invent one.
 */

const respond = (body = 'ok') =>
  ({ ok: true, status: 200, text: () => Promise.resolve(body) }) as unknown as Response;

beforeEach(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  jest.useRealTimers();
});

it('passes a timely response straight through', async () => {
  const underlying = jest.fn(() => Promise.resolve(respond()));

  const response = await boundedFetch(1000, underlying as unknown as typeof fetch)(
    'https://example.test/x'
  );

  expect(response.status).toBe(200);
});

it('gives up once the deadline passes, so the screen can say something', async () => {
  // The whole point: a hung request has to become a failure, because every
  // message this app shows about connectivity hangs off a rejection.
  const underlying = jest.fn(
    (_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new Error('Aborted')));
      })
  );

  const pending = boundedFetch(1000, underlying as unknown as typeof fetch)(
    'https://example.test/x'
  );
  const settled = expect(pending).rejects.toThrow();

  jest.advanceTimersByTime(1001);
  await settled;
});

it('leaves a caller who brought their own signal alone', async () => {
  // The room's own cancellation, and the reconnect loop's. A deadline imposed
  // on top of those would cut short a caller that is already managing its own
  // lifetime, which is how a working stream dies at thirty seconds.
  const mine = new AbortController();
  const underlying = jest.fn(() => Promise.resolve(respond()));

  await boundedFetch(1000, underlying as unknown as typeof fetch)('https://example.test/x', {
    signal: mine.signal,
  });

  expect(
    (underlying as jest.Mock).mock.calls[0]![1].signal
  ).toBe(mine.signal);
});

it('bounds an upload far more loosely than a request', () => {
  // A deck is megabytes over whatever connection the user has. The ceiling
  // exists to catch a dead socket, not to cut off a slow one, and the two
  // cases are minutes apart.
  expect(UPLOAD_TIMEOUT_MS).toBeGreaterThan(REQUEST_TIMEOUT_MS * 2);
});
