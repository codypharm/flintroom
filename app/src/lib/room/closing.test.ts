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
  // held on a screen because a request is hanging.
  const hangUp = jest.fn();

  await closeRoom({
    tell: () => new Promise(() => {}),
    hangUp,
    patience: 10,
    confirmation: 20,
  });

  expect(hangUp).toHaveBeenCalled();
});

/**
 * Whether the server *accepted* the ending, which is a different question to
 * whether the line is down — and the caller needs both.
 *
 * Reported 2026-09-19: ending a room landed on a debrief that refused to
 * open, saying the room was still running. The screen navigated on a fixed
 * beat that had no relationship to this call, so it arrived before the room
 * had settled. `POST /sessions/{id}/end` settles synchronously and returns
 * the settled room, so a resolved `tell` is the one trustworthy signal that
 * the debrief is ready to read.
 */
describe('reporting whether the room was settled', () => {
  it('confirms an ending the server accepted', async () => {
    await expect(closeRoom({ tell: async () => {}, hangUp: () => {} })).resolves.toBe(
      true
    );
  });

  it('does not confirm an ending the server never answered', async () => {
    await expect(
      closeRoom({
        tell: () => new Promise(() => {}),
        hangUp: () => {},
        patience: 10,
        confirmation: 20,
      })
    ).resolves.toBe(false);
  });

  it('does not confirm an ending the server refused', async () => {
    await expect(
      closeRoom({
        tell: async () => {
          throw new Error('offline');
        },
        hangUp: () => {},
      })
    ).resolves.toBe(false);
  });

  it('keeps waiting for the answer after the line is already down', async () => {
    // The two deadlines are deliberately different. The microphone is live
    // until `hangUp`, so that cannot wait — but the confirmation is only a
    // question about where to navigate, and giving up on it early is what put
    // somebody on a debrief that was not ready.
    //
    // A late `tell` still settles the room correctly: hanging up first only
    // opens the reconnect window, and the session stays `active` inside it.
    const order: string[] = [];

    const settled = await closeRoom({
      tell: () =>
        new Promise<void>((resolve) =>
          setTimeout(() => {
            order.push('told');
            resolve();
          }, 40)
        ),
      hangUp: () => order.push('hung up'),
      patience: 10,
      confirmation: 200,
    });

    expect(order).toEqual(['hung up', 'told']);
    expect(settled).toBe(true);
  });
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
