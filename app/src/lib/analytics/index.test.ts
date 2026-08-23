import { createAnalytics } from './index';

/**
 * Fire and forget, with both halves load-bearing: the fire is one small
 * authenticated POST, and the forget is that no failure — network, server,
 * or a token that cannot be minted — ever reaches the screen that tracked.
 */

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

it('reports a moment as one authenticated POST', async () => {
  const fetcher = jest.fn().mockResolvedValue({ ok: true, status: 202 });
  const analytics = createAnalytics({
    baseUrl: 'https://flintroom.test',
    accessToken: async () => 'a-token',
    fetch: fetcher as unknown as typeof fetch,
  });

  analytics.track('app_open');
  await flush();

  const [url, init] = fetcher.mock.calls[0];
  expect(url).toBe('https://flintroom.test/v1/events');
  expect(init.method).toBe('POST');
  expect(init.headers.Authorization).toBe('Bearer a-token');
  expect(JSON.parse(init.body)).toEqual({ events: [{ name: 'app_open' }] });
});

it('loses a report to a dead network without anybody noticing', async () => {
  const fetcher = jest.fn().mockRejectedValue(new Error('offline'));
  const analytics = createAnalytics({
    baseUrl: 'https://flintroom.test',
    accessToken: async () => 'a-token',
    fetch: fetcher as unknown as typeof fetch,
  });

  expect(() => analytics.track('app_open')).not.toThrow();
  await flush();
});

it('loses a report to a missing credential the same way', async () => {
  const fetcher = jest.fn();
  const analytics = createAnalytics({
    baseUrl: 'https://flintroom.test',
    accessToken: async () => {
      throw new Error('signed out mid-flight');
    },
    fetch: fetcher as unknown as typeof fetch,
  });

  expect(() => analytics.track('app_open')).not.toThrow();
  await flush();
  expect(fetcher).not.toHaveBeenCalled();
});
