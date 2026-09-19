/**
 * The order a room is closed in, which decides how it is recorded.
 *
 * **#82: every room in the dev database had ended as `client_disconnect` —
 * five of five, not "usually".** The old code read:
 *
 * ```ts
 * void sessions.end(settled).catch(() => undefined);
 * room.current?.leave();
 * ```
 *
 * with a comment above it saying *"the intent first, then the socket"*. That is
 * what it meant and not what it did: `void` does not wait, so a local socket
 * close raced a network round trip and won every time. The server saw the
 * disconnect first and settled the room as a dropped line, which its own
 * `EndReason` enum says is a different event to the business than somebody
 * deciding they are done.
 *
 * A function rather than four lines inside a component, because the ORDER is
 * the decision and an order that only exists inside a `useCallback` cannot be
 * tested — which is exactly how a comment came to describe behaviour the code
 * did not have.
 */

export interface Closing {
  /** Tell the server the presenter is finished. */
  tell(): Promise<void>;
  /** Drop the socket. Called exactly once, whatever `tell` does. */
  hangUp(): void;
  /**
   * How long to wait for the server before dropping the line anyway.
   *
   * The room is over either way, and the microphone is live until this fires,
   * so a presenter who has finished must never be held on a screen by a
   * hanging request.
   *
   * **The old note here said the worst case of giving up was the reaper
   * settling an abandoned room, "so the worst case is the old behaviour".
   * That stopped being true when the reconnect window landed.** Hanging up
   * without telling the server now opens a thirty-second window on a room the
   * presenter deliberately ended, and it stays `active` for all of it. Which
   * is why giving up here no longer decides anything except the socket.
   */
  patience?: number;
  /**
   * How long to keep waiting for the server's answer after the line is down.
   *
   * A second, longer deadline, because it answers a different question. The
   * microphone cannot wait; *where to navigate* can. `POST /sessions/{id}/end`
   * settles the room synchronously and returns it settled, so a resolved
   * `tell` is the only trustworthy signal that the debrief is ready to read.
   *
   * Bounded rather than unbounded for the obvious reason: a request that never
   * answers must not strand somebody on the ending beat forever.
   */
  confirmation?: number;
}

const PATIENCE_MS = 2000;
const CONFIRMATION_MS = 5000;

/**
 * Closes the room, and reports whether the server accepted the ending.
 *
 * The return value is the 2026-09-19 addition. Ending a room landed on a
 * debrief that refused to open, saying the room was still running: the screen
 * navigated on a fixed beat that had no relationship to this call, so it
 * arrived while settlement was still in flight — or, when `tell` lost the race
 * above, before the server had been told at all.
 *
 * `true` means the room is settled and the debrief will read. `false` means we
 * do not know, which is not the same as knowing it failed.
 */
export async function closeRoom({
  tell,
  hangUp,
  patience = PATIENCE_MS,
  confirmation = CONFIRMATION_MS,
}: Closing): Promise<boolean> {
  let dropped = false;
  const drop = () => {
    // Guarded rather than trusted: the timer and the answer both arrive here,
    // and a second `leave()` is a second teardown.
    if (dropped) {
      return;
    }
    dropped = true;
    hangUp();
  };

  // Swallowed rather than propagated: a refusal is not a reason to keep a dead
  // socket open, and the caller reads the boolean instead.
  const told = tell().then(
    () => true,
    () => false
  );

  const line = setTimeout(drop, patience);
  // Whichever way it goes, the line comes down as soon as the answer lands —
  // there is no reason to hold a microphone open for the rest of the patience.
  void told.finally(() => {
    clearTimeout(line);
    drop();
  });

  let giveUp: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      told,
      new Promise<boolean>((resolve) => {
        giveUp = setTimeout(() => resolve(false), confirmation);
      }),
    ]);
  } finally {
    if (giveUp !== undefined) {
      clearTimeout(giveUp);
    }
  }
}
