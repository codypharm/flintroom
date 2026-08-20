import { closeRoom } from './closing';

/**
 * #82 — every room in the dev database ended as `client_disconnect`. Five out
 * of five, not "usually".
 */

function spies() {
  const order: string[] = [];
  return {
    order,
    tell: jest.fn(async () => {
      order.push('told');
    }),
    hangUp: jest.fn(() => {
      order.push('hung up');
    }),
  };
}

it('tells the server before it drops the line', async () => {
  // The old code read `void sessions.end(id)` then `room.leave()` on the next
  // line. `void` does not wait, so a local socket close raced a network round
  // trip and won every time — the server saw the disconnect first and settled
  // the room as a dropped line. The comment above it claimed "the intent
  // first, then the socket", which is what it MEANT and not what it did.
  const { order, tell, hangUp } = spies();

  await closeRoom({ tell, hangUp });

  expect(order).toEqual(['told', 'hung up']);
});

it('drops the line anyway when the server will not answer', async () => {
  // The room is over either way. A presenter who has finished must never be
  // held on a screen because a request is hanging — the reaper settles an
  // abandoned room and refunds it, so the worst case is the old behaviour.
  const hangUp = jest.fn();

  await closeRoom({
    tell: () => new Promise(() => {}),
    hangUp,
    patience: 10,
  });

  expect(hangUp).toHaveBeenCalled();
});

it('does not wait the full timeout when the server answers quickly', async () => {
  const started = Date.now();

  await closeRoom({ tell: async () => {}, hangUp: () => {}, patience: 5000 });

  expect(Date.now() - started).toBeLessThan(1000);
});

it('drops the line when the request fails outright', async () => {
  // A refusal is not a reason to keep a dead socket open.
  const hangUp = jest.fn();

  await closeRoom({
    tell: async () => {
      throw new Error('offline');
    },
    hangUp,
  });

  expect(hangUp).toHaveBeenCalled();
});

it('hangs up exactly once', async () => {
  // Belt and braces: the timeout and the answer must not both fire it.
  const hangUp = jest.fn();

  await closeRoom({ tell: async () => {}, hangUp, patience: 10 });
  await new Promise((r) => setTimeout(r, 30));

  expect(hangUp).toHaveBeenCalledTimes(1);
});
