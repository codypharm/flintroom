import { reconnectRoom, type Attempt } from './reconnect';

/**
 * The way back into a dropped room — docs/reconnect.md, the client's half.
 *
 * The loop's exit conditions are the design: `joined` means the presenter is
 * back in the same room; `gone` means the server said there is no live room
 * to rejoin — which is exactly what the re-mint answers once the reaper has
 * settled it, so it doubles as the signal that the debrief is ready; `retry`
 * covers everything transient. The outer bound exists only for a server that
 * never answers at all.
 */

function scripted(results: Attempt[]): {
  attempt: () => Promise<Attempt>;
  calls: () => number;
} {
  let call = 0;
  return {
    attempt: () => {
      const next = results[Math.min(call, results.length - 1)];
      call += 1;
      return Promise.resolve(next);
    },
    calls: () => call,
  };
}

const instantly = () => Promise.resolve();

it('lands back in the room on the first answer that lets it', async () => {
  const tries = scripted(['retry', 'retry', 'joined']);

  const back = await reconnectRoom({ attempt: tries.attempt, sleep: instantly });

  expect(back).toBe('joined');
  expect(tries.calls()).toBe(3);
});

it('stops the moment the server says there is no room to rejoin', async () => {
  const tries = scripted(['retry', 'gone', 'joined']);

  const back = await reconnectRoom({ attempt: tries.attempt, sleep: instantly });

  expect(back).toBe('gone');
  expect(tries.calls()).toBe(2);
});

it('gives up when the window is spent without an answer either way', async () => {
  let clock = 0;
  const tries = scripted(['retry']);

  const back = await reconnectRoom({
    attempt: tries.attempt,
    sleep: () => {
      clock += 10_000;
      return Promise.resolve();
    },
    now: () => clock,
    windowMs: 25_000,
  });

  expect(back).toBe('gone');
  // 0ms, 10s and 20s are inside the window; 30s is not.
  expect(tries.calls()).toBe(3);
});

it('treats an attempt that throws as one more transient failure', async () => {
  let call = 0;

  const back = await reconnectRoom({
    attempt: () => {
      call += 1;
      if (call === 1) {
        return Promise.reject(new Error('network still down'));
      }
      return Promise.resolve('joined');
    },
    sleep: instantly,
  });

  expect(back).toBe('joined');
  expect(call).toBe(2);
});

it('paces its attempts instead of hammering a recovering network', async () => {
  const waits: number[] = [];
  const tries = scripted(['retry', 'joined']);

  await reconnectRoom({
    attempt: tries.attempt,
    sleep: (ms) => {
      waits.push(ms);
      return Promise.resolve();
    },
    delayMs: 2_000,
  });

  expect(waits).toEqual([2_000]);
});
